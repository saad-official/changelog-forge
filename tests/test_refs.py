import pytest

from changelog_forge.collect.refs import (
    TargetError,
    parse_compare_url,
    parse_range,
    parse_repo,
    resolve_target,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("fastapi/fastapi", ("fastapi", "fastapi")),
        ("  vercel/ai  ", ("vercel", "ai")),
        ("https://github.com/withastro/astro", ("withastro", "astro")),
        ("https://github.com/withastro/astro.git", ("withastro", "astro")),
        ("drizzle-team/drizzle-orm", ("drizzle-team", "drizzle-orm")),
    ],
)
def test_parse_repo_accepts_names_and_urls(text, expected):
    assert parse_repo(text) == expected


@pytest.mark.parametrize("text", ["fastapi", "a/b/c", "https://gitlab.com/a/b", "-bad/x", "a/.."])
def test_parse_repo_rejects_garbage(text):
    with pytest.raises(TargetError):
        parse_repo(text)


def test_two_and_three_dot_ranges_mean_the_same():
    assert parse_range("v1.2.0..v1.3.0") == ("v1.2.0", "v1.3.0")
    assert parse_range("v1.2.0...v1.3.0") == ("v1.2.0", "v1.3.0")
    assert parse_range("ai@7.0.1..ai@7.0.2") == ("ai@7.0.1", "ai@7.0.2")


@pytest.mark.parametrize("text", ["v1.2.0", "..v1", "v1..", "a b..c"])
def test_bad_ranges_are_rejected(text):
    with pytest.raises(TargetError):
        parse_range(text)


def test_compare_url_is_parsed_including_package_tags():
    spec = parse_compare_url("https://github.com/vercel/ai/compare/ai%407.0.1...ai%407.0.2")
    assert (spec.repo, spec.base, spec.head) == ("vercel/ai", "ai@7.0.1", "ai@7.0.2")
    assert parse_compare_url("https://github.com/a/b/compare/v1...v2.diff").head == "v2"


def test_compare_url_must_be_github():
    with pytest.raises(TargetError):
        parse_compare_url("https://example.com/a/b/compare/v1...v2")


def test_resolve_target_forms():
    assert resolve_target("a/b", "v1", "v2").compare_url == "https://github.com/a/b/compare/v1...v2"
    assert resolve_target("a/b", "v1..v2").head == "v2"
    url = resolve_target("https://github.com/a/b/compare/v1...v2", head="v3")
    assert (url.base, url.head) == ("v1", "v3")
    with pytest.raises(TargetError, match="range is required"):
        resolve_target("a/b")
