"""Collect: GitHub REST -> CollectedRange.

Calls made for one range, and why each exists:

    GET /repos/{o}/{r}                         default branch, and whether the repo is
                                               private (private data is never cached)
    GET /repos/{o}/{r}/compare/{base}...{head} the commits, 100 per page
    GET /repos/{o}/{r}/commits/{sha}/pulls     the PR each commit came from (title, body,
                                               labels): one call per *uncached* commit
    GET /repos/{o}/{r}/commits/{sha}           files touched, only when authenticated

Three things keep this inside GitHub's limits (60 req/h anonymous, 5,000 with a token):

  1. The `(repo, sha)` cache. A commit is immutable, so its PR association is fetched once,
     ever, and re-runs over overlapping ranges only pay for new commits.
  2. ETags on the repo and compare calls. A 304 Not Modified does not count against an
     authenticated client's primary rate limit, and costs no parsing.
  3. A pre-flight budget check: after the compare call we know exactly how many lookups
     remain, so a range that cannot finish is refused up front with the reset time, rather
     than failing at commit 57 of 120.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from ..models import CollectedRange, CommitRecord
from .refs import RangeSpec

log = logging.getLogger(__name__)

API_URL = "https://api.github.com"
MAX_STORED_BODY = 3000  # normalise truncates to 1,500; keep a little more in the cache
MAX_FILES = 100
PAGE_SIZE = 100
LOOKUP_WORKERS = 8


class GitHubError(Exception):
    """A user-facing collection failure. `status` and `code` are what the API returns
    (docs/api.md lists the codes the web app relies on)."""

    status = 502
    code = "github_error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class RepoNotFound(GitHubError):
    status = 404
    code = "repo_not_found"


class BadRange(GitHubError):
    """A ref in the range does not exist (GitHub answers the compare with 404 or 422)."""

    status = 404
    code = "range_not_found"


class EmptyRange(GitHubError):
    status = 422
    code = "empty_range"


class TooManyCommits(GitHubError):
    status = 422
    code = "commit_cap"


class BadToken(GitHubError):
    status = 401
    code = "unauthorized"


class Forbidden(GitHubError):
    status = 403
    code = "unauthorized"


class RateLimited(GitHubError):
    status = 429
    code = "rate_limited"

    def __init__(self, message: str, *, reset_at: datetime | None = None, retry_after: int = 0):
        super().__init__(message)
        self.reset_at = reset_at
        if not retry_after and reset_at is not None:
            retry_after = max(1, int((reset_at - datetime.now(UTC)).total_seconds()))
        self.retry_after = retry_after or 60


class CommitCache(Protocol):
    """The slice of `Store` that collection needs (see db.store)."""

    def upsert_repo(self, owner: str, name: str, default_branch: str | None) -> int: ...
    def get_commits(self, repo_id: int, shas: list[str]) -> dict[str, CommitRecord]: ...
    def put_commits(self, repo_id: int, commits: list[CommitRecord]) -> None: ...
    def get_http_cache(self, key: str) -> tuple[str, Any] | None: ...
    def put_http_cache(self, key: str, etag: str, body: Any) -> None: ...


ProgressFn = Callable[[str, int, int], None]

_SQUASH_PR = re.compile(r"\(#(\d+)\)\s*$")
_MERGE_PR = re.compile(r"^Merge pull request #(\d+)")


class GitHubClient:
    def __init__(
        self,
        cache: CommitCache,
        token: str | None = None,
        *,
        http: httpx.Client | None = None,
        base_url: str = API_URL,
        max_commits: int = 400,
        fetch_files: bool | None = None,
    ):
        self.cache = cache
        self.max_commits = max_commits
        # Files cost one extra request per commit. Worth it with 5,000 req/h, not with 60.
        self.fetch_files = bool(token) if fetch_files is None else fetch_files
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "changelog-forge",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.http = http or httpx.Client(timeout=20.0)
        self._headers = headers
        self._base_url = base_url.rstrip("/")
        self.rate_remaining: int | None = None
        self.rate_reset: datetime | None = None
        self.api_calls = 0
        self.cache_hits = 0

    # ----------------------------------------------------------------- HTTP plumbing

    def _track_rate(self, response: httpx.Response) -> None:
        remaining = response.headers.get("x-ratelimit-remaining")
        reset = response.headers.get("x-ratelimit-reset")
        if remaining is not None and remaining.isdigit():
            self.rate_remaining = int(remaining)
        if reset is not None and reset.isdigit():
            self.rate_reset = datetime.fromtimestamp(int(reset), tz=UTC)

    def _raise_for(
        self, response: httpx.Response, what: str, not_found: type[GitHubError] = RepoNotFound
    ) -> None:
        status = response.status_code
        if status in (403, 429):
            retry_after = response.headers.get("retry-after")
            if response.headers.get("x-ratelimit-remaining") == "0" or retry_after:
                when = self.rate_reset.strftime("%H:%M UTC") if self.rate_reset else "soon"
                raise RateLimited(
                    f"GitHub rate limit reached while fetching {what}; it resets at {when}. "
                    "Add a GitHub token to raise the limit from 60 to 5,000 requests/hour.",
                    reset_at=self.rate_reset,
                    retry_after=int(retry_after) if retry_after and retry_after.isdigit() else 0,
                )
            raise Forbidden(f"GitHub refused access to {what} (403).")
        if status == 401:
            raise BadToken("GitHub rejected the token (401). Check it has read access.")
        if status == 404 and not_found is BadRange:
            raise BadRange(f"{what}: one of the refs does not exist in this repository.")
        if status == 404:
            raise RepoNotFound(
                f"{what} was not found. It may not exist, or it may be private: "
                "private repositories need a token that can read them."
            )
        if status == 422:
            raise BadRange(f"GitHub could not compare {what}: check both refs exist.")
        if status >= 500:
            raise GitHubError(f"GitHub returned {status} for {what}; try again shortly.")
        raise GitHubError(f"unexpected GitHub response {status} for {what}.")

    def _get(
        self,
        path: str,
        *,
        what: str,
        params: dict[str, Any] | None = None,
        cache_key: str = "",
        not_found: type[GitHubError] = RepoNotFound,
    ) -> tuple[Any, bool, str | None]:
        """GET a JSON document. Returns (body, served_from_cache, etag).

        With `cache_key`, sends `If-None-Match` and serves the cached body on 304. The cached
        body is whatever `_slim` produced, never the raw response: a compare response can
        carry megabytes of patches we have no use for.
        """
        headers = dict(self._headers)
        cached = self.cache.get_http_cache(cache_key) if cache_key else None
        if cached:
            headers["If-None-Match"] = cached[0]
        url = f"{self._base_url}{path}"
        response: httpx.Response | None = None
        for attempt in (1, 2):  # one retry for GitHub's occasional 502 on big compares
            try:
                response = self.http.get(url, params=params, headers=headers)
            except httpx.TransportError as exc:
                if attempt == 2:
                    raise GitHubError(f"could not reach GitHub for {what}: {exc}") from exc
                continue
            if response.status_code < 500:
                break
        assert response is not None
        self.api_calls += 1
        self._track_rate(response)
        if response.status_code == 304 and cached:
            self.cache_hits += 1
            return cached[1], True, cached[0]
        if response.status_code != 200:
            self._raise_for(response, what, not_found)
        return response.json(), False, response.headers.get("etag")

    # ----------------------------------------------------------------- the calls

    def repo_info(self, spec: RangeSpec) -> dict[str, Any]:
        key = f"repo:{spec.repo.lower()}"
        body, from_cache, etag = self._get(
            f"/repos/{spec.repo}", what=f"repository {spec.repo}", cache_key=key
        )
        slim = {
            "default_branch": body.get("default_branch"),
            "private": bool(body.get("private")),
        }
        if not from_cache and not slim["private"] and etag:
            self.cache.put_http_cache(key, etag, slim)
        return slim

    def _compare_page(self, spec: RangeSpec, page: int, persist: bool) -> dict[str, Any]:
        base, head = quote(spec.base, safe="/@^~"), quote(spec.head, safe="/@^~")
        key = f"compare:{spec.repo.lower()}:{spec.base}...{spec.head}:{page}"
        body, from_cache, etag = self._get(
            f"/repos/{spec.repo}/compare/{base}...{head}",
            what=f"{spec.repo} {spec.base}...{spec.head}",
            params={"per_page": PAGE_SIZE, "page": page},
            cache_key=key if persist else "",
            not_found=BadRange,
        )
        if from_cache:
            return body
        slim = {
            "total_commits": body.get("total_commits", 0),
            "html_url": body.get("html_url"),
            "commits": [
                {
                    "sha": c["sha"],
                    "message": c.get("commit", {}).get("message", ""),
                    "author": (c.get("author") or {}).get("login")
                    or (c.get("commit", {}).get("author") or {}).get("name"),
                    "date": (c.get("commit", {}).get("author") or {}).get("date"),
                    "parents": len(c.get("parents") or []),
                    "html_url": c.get("html_url", ""),
                }
                for c in body.get("commits", [])
            ],
        }
        if persist and etag:
            self.cache.put_http_cache(key, etag, slim)
        return slim

    def _lookup(self, spec: RangeSpec, raw: dict[str, Any]) -> CommitRecord:
        """Enrich one commit with its pull request (and files, when affordable)."""
        sha = raw["sha"]
        record = CommitRecord(
            sha=sha,
            message=raw["message"],
            author=raw.get("author"),
            date=raw.get("date"),
            parents=raw.get("parents", 1),
            html_url=raw.get("html_url") or f"https://github.com/{spec.repo}/commit/{sha}",
        )
        pulls, _, _ = self._get(
            f"/repos/{spec.repo}/commits/{sha}/pulls", what=f"PRs for {sha[:7]}"
        )
        pr = _pick_pr(pulls, sha)
        if pr is not None:
            record.pr_number = pr["number"]
            record.pr_title = pr.get("title")
            record.pr_body = (pr.get("body") or "")[:MAX_STORED_BODY]
            record.pr_url = pr.get("html_url")
            record.labels = [label["name"] for label in pr.get("labels", []) if "name" in label]
        else:
            # No PR association from the API: fall back to the conventions GitHub writes
            # into commit messages, so squash and merge commits still link to their PR.
            match = _SQUASH_PR.search(record.subject) or _MERGE_PR.match(record.subject)
            if match:
                record.pr_number = int(match.group(1))
                record.pr_url = f"https://github.com/{spec.repo}/pull/{record.pr_number}"
        if self.fetch_files:
            detail, _, _ = self._get(f"/repos/{spec.repo}/commits/{sha}", what=f"commit {sha[:7]}")
            record.files = [f["filename"] for f in detail.get("files", [])][:MAX_FILES]
        return record

    def collect(self, spec: RangeSpec, on_progress: ProgressFn | None = None) -> CollectedRange:
        progress = on_progress or (lambda stage, current, total: None)
        info = self.repo_info(spec)
        persist = not info["private"]
        repo_id = self.cache.upsert_repo(spec.owner, spec.name, info["default_branch"])

        first = self._compare_page(spec, 1, persist)
        total = int(first.get("total_commits") or 0)
        if total == 0:
            raise EmptyRange(f"{spec.base}...{spec.head} contains no commits.")
        if total > self.max_commits:
            raise TooManyCommits(
                f"{spec.base}...{spec.head} has {total} commits; the limit is "
                f"{self.max_commits} per run. Pick a narrower range."
            )
        raw_commits = list(first["commits"])
        page = 2
        while len(raw_commits) < total:
            more = self._compare_page(spec, page, persist)["commits"]
            if not more:
                break
            raw_commits.extend(more)
            page += 1
        progress("collecting", 0, len(raw_commits))

        cached = self.cache.get_commits(repo_id, [c["sha"] for c in raw_commits])
        missing = [c for c in raw_commits if c["sha"] not in cached]
        self.cache_hits += len(raw_commits) - len(missing)
        needed = len(missing) * (2 if self.fetch_files else 1)
        if self.rate_remaining is not None and needed > self.rate_remaining:
            when = self.rate_reset.strftime("%H:%M UTC") if self.rate_reset else "soon"
            raise RateLimited(
                f"This range needs about {needed} more GitHub API calls but only "
                f"{self.rate_remaining} remain until {when}. Add a GitHub token, or retry later.",
                reset_at=self.rate_reset,
            )

        fetched: dict[str, CommitRecord] = {}
        if missing:
            done = 0
            with ThreadPoolExecutor(max_workers=LOOKUP_WORKERS) as pool:
                for record in pool.map(lambda raw: self._lookup(spec, raw), missing):
                    fetched[record.sha] = record
                    done += 1
                    if done % 10 == 0 or done == len(missing):
                        progress("collecting", done, len(missing))
            if persist:
                self.cache.put_commits(repo_id, list(fetched.values()))

        commits = [cached.get(c["sha"]) or fetched[c["sha"]] for c in raw_commits]
        return CollectedRange(
            repo=spec.repo,
            base=spec.base,
            head=spec.head,
            compare_url=first.get("html_url") or spec.compare_url,
            default_branch=info["default_branch"],
            private=info["private"],
            total_commits=total,
            commits=commits,
            api_calls=self.api_calls,
            cache_hits=self.cache_hits,
        )

    def close(self) -> None:
        self.http.close()


def _pick_pr(pulls: Any, sha: str) -> dict[str, Any] | None:
    """A commit can appear in several PRs (backports, stacked PRs). Prefer the one that
    merged *this* commit, then any merged PR, then whatever GitHub listed first."""
    if not isinstance(pulls, list) or not pulls:
        return None
    for pr in pulls:
        if pr.get("merge_commit_sha") == sha:
            return pr
    for pr in pulls:
        if pr.get("merged_at"):
            return pr
    return pulls[0]
