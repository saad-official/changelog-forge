import time

import httpx
import pytest
import respx

from changelog_forge.collect.github import (
    API_URL,
    BadRange,
    BadToken,
    EmptyRange,
    GitHubClient,
    RateLimited,
    RepoNotFound,
    TooManyCommits,
)
from changelog_forge.collect.refs import RangeSpec
from changelog_forge.db import MemoryStore

from .conftest import sha

SPEC = RangeSpec(owner="acme", name="widgets", base="v1", head="v2")
REPO_URL = f"{API_URL}/repos/acme/widgets"
COMPARE_URL = f"{REPO_URL}/compare/v1...v2"


def raw_commit(seed: str, message: str, parents: int = 1) -> dict:
    return {
        "sha": sha(seed),
        "commit": {"message": message, "author": {"name": "Dev", "date": "2026-01-01T00:00:00Z"}},
        "author": {"login": "dev"},
        "parents": [{}] * parents,
        "html_url": f"https://github.com/acme/widgets/commit/{sha(seed)}",
    }


def rate_headers(remaining: int = 4999) -> dict[str, str]:
    return {
        "x-ratelimit-remaining": str(remaining),
        "x-ratelimit-reset": str(int(time.time()) + 600),
    }


def mock_repo(router, private: bool = False):
    return router.get(REPO_URL).mock(
        return_value=httpx.Response(
            200,
            json={"default_branch": "main", "private": private},
            headers={"etag": '"repo-1"', **rate_headers()},
        )
    )


def mock_pulls(router, seed: str, pulls: list[dict]):
    return router.get(f"{REPO_URL}/commits/{sha(seed)}/pulls").mock(
        return_value=httpx.Response(200, json=pulls, headers=rate_headers())
    )


def pr(number: int, merge_sha: str | None = None, merged: bool = True) -> dict:
    return {
        "number": number,
        "title": f"PR {number}",
        "body": "body",
        "html_url": f"https://github.com/acme/widgets/pull/{number}",
        "labels": [{"name": "bug"}],
        "merge_commit_sha": merge_sha,
        "merged_at": "2026-01-01T00:00:00Z" if merged else None,
    }


@respx.mock
def test_collect_paginates_and_enriches_commits_with_their_prs():
    mock_repo(respx)
    page1 = [raw_commit(f"c{i}", f"commit {i}") for i in range(100)]
    page2 = [raw_commit("c100", "Fix it (#5)")]
    compare = respx.get(COMPARE_URL)
    compare.side_effect = [
        httpx.Response(
            200,
            json={"total_commits": 101, "html_url": "https://github.com/x", "commits": page1},
            headers={"etag": '"p1"', **rate_headers()},
        ),
        httpx.Response(200, json={"total_commits": 101, "commits": page2}, headers=rate_headers()),
    ]
    # respx matches routes in registration order: the specific route goes first.
    mock_pulls(respx, "c3", [pr(3, merged=False), pr(4, merge_sha=sha("c3"))])
    respx.get(url__regex=rf"{REPO_URL}/commits/[0-9a-f]+/pulls").mock(
        return_value=httpx.Response(200, json=[], headers=rate_headers())
    )

    store = MemoryStore()
    progress = []
    result = GitHubClient(store).collect(SPEC, on_progress=lambda *a: progress.append(a))

    assert len(result.commits) == 101 and result.total_commits == 101
    assert compare.call_count == 2
    by_sha = {c.sha: c for c in result.commits}
    assert by_sha[sha("c3")].pr_number == 4  # the PR that merged this commit wins
    assert by_sha[sha("c3")].labels == ["bug"]
    assert by_sha[sha("c100")].pr_number == 5  # squash convention fallback
    assert by_sha[sha("c1")].files is None  # anonymous: files not fetched
    assert progress[-1] == ("collecting", 101, 101)


@respx.mock
def test_a_second_run_uses_the_sha_cache_and_etags():
    mock_repo(respx)
    commits = [raw_commit("a", "one"), raw_commit("b", "two")]
    compare = respx.get(COMPARE_URL)
    compare.side_effect = [
        httpx.Response(
            200, json={"total_commits": 2, "commits": commits}, headers={"etag": '"c1"'}
        ),
        httpx.Response(304),
    ]
    pulls = respx.get(url__regex=rf"{REPO_URL}/commits/[0-9a-f]+/pulls").mock(
        return_value=httpx.Response(200, json=[pr(9)])
    )
    store = MemoryStore()
    first = GitHubClient(store).collect(SPEC)
    assert pulls.call_count == 2

    respx.get(REPO_URL).mock(return_value=httpx.Response(304))
    client = GitHubClient(store)
    second = client.collect(SPEC)
    assert pulls.call_count == 2  # no new lookups: every sha came from the cache
    assert compare.calls.last.request.headers["if-none-match"] == '"c1"'
    assert [c.sha for c in second.commits] == [c.sha for c in first.commits]
    assert second.cache_hits >= 3  # repo + compare 304s, plus 2 cached commits


@respx.mock
def test_token_is_sent_and_files_are_fetched_when_authenticated():
    mock_repo(respx)
    respx.get(COMPARE_URL).mock(
        return_value=httpx.Response(
            200, json={"total_commits": 1, "commits": [raw_commit("a", "x")]}
        )
    )
    mock_pulls(respx, "a", [])
    detail = respx.get(f"{REPO_URL}/commits/{sha('a')}").mock(
        return_value=httpx.Response(200, json={"files": [{"filename": "src/app.py"}]})
    )
    result = GitHubClient(MemoryStore(), token="tok").collect(SPEC)
    assert detail.called
    assert result.commits[0].files == ["src/app.py"]
    assert respx.calls[0].request.headers["authorization"] == "Bearer tok"


@respx.mock
def test_private_repositories_are_never_cached():
    mock_repo(respx, private=True)
    respx.get(COMPARE_URL).mock(
        return_value=httpx.Response(
            200, json={"total_commits": 1, "commits": [raw_commit("a", "x")]}, headers={"etag": "e"}
        )
    )
    mock_pulls(respx, "a", [])
    store = MemoryStore()
    GitHubClient(store, token="t", fetch_files=False).collect(SPEC)
    assert store.get_commits(1, [sha("a")]) == {}
    assert store.get_http_cache("compare:acme/widgets:v1...v2:1") is None


@respx.mock
def test_rate_limit_is_a_typed_error_with_the_reset_time():
    reset = int(time.time()) + 1200
    respx.get(REPO_URL).mock(
        return_value=httpx.Response(
            403,
            json={"message": "API rate limit exceeded"},
            headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(reset)},
        )
    )
    with pytest.raises(RateLimited) as caught:
        GitHubClient(MemoryStore()).collect(SPEC)
    assert caught.value.reset_at is not None
    assert int(caught.value.reset_at.timestamp()) == reset
    assert 1100 < caught.value.retry_after <= 1200
    assert caught.value.code == "rate_limited" and caught.value.status == 429


@respx.mock
def test_a_range_that_cannot_finish_is_refused_before_any_lookup():
    mock_repo(respx)
    respx.get(COMPARE_URL).mock(
        return_value=httpx.Response(
            200,
            json={"total_commits": 3, "commits": [raw_commit(str(i), "x") for i in range(3)]},
            headers=rate_headers(remaining=2),
        )
    )
    pulls = respx.get(url__regex=r".*/pulls$")
    with pytest.raises(RateLimited, match="needs about 3"):
        GitHubClient(MemoryStore()).collect(SPEC)
    assert not pulls.called


@respx.mock
def test_commit_cap():
    mock_repo(respx)
    respx.get(COMPARE_URL).mock(
        return_value=httpx.Response(200, json={"total_commits": 401, "commits": []})
    )
    with pytest.raises(TooManyCommits, match="401 commits") as caught:
        GitHubClient(MemoryStore()).collect(SPEC)
    assert caught.value.code == "commit_cap"


@respx.mock
def test_empty_range():
    mock_repo(respx)
    respx.get(COMPARE_URL).mock(
        return_value=httpx.Response(200, json={"total_commits": 0, "commits": []})
    )
    with pytest.raises(EmptyRange):
        GitHubClient(MemoryStore()).collect(SPEC)


@respx.mock
@pytest.mark.parametrize(
    ("repo_status", "compare_status", "error", "code"),
    [
        (404, None, RepoNotFound, "repo_not_found"),
        (401, None, BadToken, "unauthorized"),
        (200, 404, BadRange, "range_not_found"),
        (200, 422, BadRange, "range_not_found"),
    ],
)
def test_http_errors_map_to_typed_errors(repo_status, compare_status, error, code):
    respx.get(REPO_URL).mock(
        return_value=httpx.Response(repo_status, json={"default_branch": "main", "private": False})
    )
    if compare_status:
        respx.get(COMPARE_URL).mock(return_value=httpx.Response(compare_status, json={}))
    with pytest.raises(error) as caught:
        GitHubClient(MemoryStore()).collect(SPEC)
    assert caught.value.code == code
