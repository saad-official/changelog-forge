"""Normalise: CommitRecord[] -> ChangeItem[].

The unit a reader cares about is a *change*, not a commit. A PR merged with a merge commit
arrives as N feature commits plus one "Merge pull request #12" commit; a squash-merged PR
arrives as one commit titled "Add X (#12)". Both must become one item carrying the PR's
title, a truncated body, labels and files, so the model sees one thing to summarise and
the reader sees one bullet.

Everything here is deterministic and cheap, which is the point: every token the model does
not have to spend un-tangling git history is a token it spends on the actual summary.
"""

from __future__ import annotations

import re
from collections import OrderedDict

from .models import ChangeItem, CollectedRange, CommitRecord

BODY_LIMIT = 1500

# type(scope)!: description   (https://www.conventionalcommits.org/en/v1.0.0/)
_CONVENTIONAL = re.compile(
    r"^(?P<type>[a-zA-Z]+)(?:\((?P<scope>[^)]*)\))?(?P<bang>!)?:\s+(?P<description>.+)$"
)
_BREAKING_FOOTER = re.compile(r"^BREAKING[ -]CHANGE:", re.MULTILINE)
_MERGE_PR = re.compile(r"^Merge pull request #(?P<number>\d+)")
_SQUASH_PR = re.compile(r"\s*\(#(?P<number>\d+)\)\s*$")
_BRANCH_MERGE = re.compile(
    r"^Merge (?:branch(?:es)?|remote-tracking branch|tag) .+"
    r"|^Merge [0-9a-f]{7,40} into [0-9a-f]{7,40}"
)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_BLANK_RUNS = re.compile(r"\n{3,}")

KNOWN_TYPES = {
    "feat",
    "fix",
    "perf",
    "docs",
    "refactor",
    "chore",
    "test",
    "build",
    "ci",
    "style",
    "revert",
    "deps",
}


class Conventional:
    __slots__ = ("breaking", "description", "scope", "type")

    def __init__(self, type_: str, scope: str | None, breaking: bool, description: str):
        self.type = type_
        self.scope = scope
        self.breaking = breaking
        self.description = description


def parse_conventional(subject: str, body: str = "") -> Conventional | None:
    """Parse a Conventional Commits subject. Unknown types are not conventional commits:
    "Fix: typo" is, "WIP: stuff" is not, which keeps false positives out of categorisation.
    """
    match = _CONVENTIONAL.match(subject.strip())
    if not match or match.group("type").lower() not in KNOWN_TYPES:
        return None
    return Conventional(
        type_=match.group("type").lower(),
        scope=(match.group("scope") or None),
        breaking=bool(match.group("bang")) or bool(_BREAKING_FOOTER.search(body or "")),
        description=match.group("description").strip(),
    )


def clean_body(text: str | None, limit: int = BODY_LIMIT) -> str:
    """Strip PR-template HTML comments, collapse blank runs, truncate to `limit` chars.

    PR templates are mostly `<!-- please describe... -->` scaffolding: pure input-token tax
    that also invites the model to summarise the template instead of the change.
    """
    if not text:
        return ""
    cleaned = _BLANK_RUNS.sub("\n\n", _HTML_COMMENT.sub("", text).replace("\r\n", "\n")).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def is_merge_commit(commit: CommitRecord) -> bool:
    return commit.parents > 1 or bool(_MERGE_PR.match(commit.subject))


def is_branch_sync(commit: CommitRecord) -> bool:
    """`Merge branch 'main' into feature`: no change of its own, pure noise for notes."""
    return commit.pr_number is None and bool(_BRANCH_MERGE.match(commit.subject))


def pr_number_for(commit: CommitRecord) -> int | None:
    """The PR a commit belongs to: the API's answer first, then the message conventions."""
    if commit.pr_number is not None:
        return commit.pr_number
    match = _MERGE_PR.match(commit.subject) or _SQUASH_PR.search(commit.subject)
    return int(match.group("number")) if match else None


def normalise(collected: CollectedRange) -> tuple[list[ChangeItem], list[str]]:
    """Group commits into ChangeItems. Returns (items, skipped_shas).

    Order is first-appearance order in the range (oldest first), which keeps prompts and
    golden-set fixtures stable across runs.
    """
    repo_url = f"https://github.com/{collected.repo}"
    by_pr: OrderedDict[int, list[CommitRecord]] = OrderedDict()
    singles: list[CommitRecord] = []
    order: list[tuple[str, int | str]] = []
    skipped: list[str] = []

    for commit in collected.commits:
        number = pr_number_for(commit)
        if number is not None:
            if number not in by_pr:
                by_pr[number] = []
                order.append(("pr", number))
            by_pr[number].append(commit)
        elif is_branch_sync(commit):
            skipped.append(commit.sha)
        else:
            singles.append(commit)
            order.append(("commit", commit.sha))

    singles_by_sha = {commit.sha: commit for commit in singles}
    items: list[ChangeItem] = []
    for kind, key in order:
        if kind == "pr":
            items.append(_pr_item(int(key), by_pr[int(key)], repo_url))
        else:
            items.append(_commit_item(singles_by_sha[str(key)], repo_url))
    return items, skipped


def _pr_item(number: int, commits: list[CommitRecord], repo_url: str) -> ChangeItem:
    # The PR metadata is identical on every commit of the PR; take the first that has it.
    meta = next((c for c in commits if c.pr_title), commits[0])
    # The merge commit's subject is "Merge pull request #12 from fork/branch": useless as a
    # title. Prefer the PR title, then a non-merge commit subject.
    content_commits = [c for c in commits if not is_merge_commit(c)] or commits
    title = meta.pr_title or _SQUASH_PR.sub("", content_commits[0].subject)
    if not meta.pr_title and is_merge_commit(content_commits[0]):
        # "Merge pull request #12 from x/y\n\nActual title" -> the body's first line
        rest = content_commits[0].message.split("\n", 1)[1:] or [""]
        title = rest[0].strip().split("\n", 1)[0] or title
    body_source = meta.pr_body if meta.pr_title else _commit_body(content_commits[0])
    conventional = parse_conventional(title, body_source or "") or next(
        (
            parsed
            for c in content_commits
            if (parsed := parse_conventional(c.subject, _commit_body(c))) is not None
        ),
        None,
    )
    files: list[str] = []
    for commit in commits:
        for path in commit.files or []:
            if path not in files:
                files.append(path)
    authors = list(OrderedDict.fromkeys(c.author for c in commits if c.author))
    return ChangeItem(
        id=f"pr-{number}",
        kind="pr",
        pr_number=number,
        title=title.strip(),
        body=clean_body(body_source),
        shas=[c.sha for c in commits],
        authors=authors,
        labels=meta.labels,
        files=files,
        conventional_type=conventional.type if conventional else None,
        conventional_scope=conventional.scope if conventional else None,
        conventional_breaking=conventional.breaking if conventional else False,
        url=meta.pr_url or f"{repo_url}/pull/{number}",
    )


def _commit_body(commit: CommitRecord) -> str:
    parts = commit.message.split("\n", 1)
    return parts[1].strip() if len(parts) > 1 else ""


def _commit_item(commit: CommitRecord, repo_url: str) -> ChangeItem:
    body = _commit_body(commit)
    conventional = parse_conventional(commit.subject, body)
    return ChangeItem(
        id=f"c-{commit.sha[:7]}",
        kind="commit",
        title=commit.subject,
        body=clean_body(body),
        shas=[commit.sha],
        authors=[commit.author] if commit.author else [],
        labels=commit.labels,
        files=list(commit.files or []),
        conventional_type=conventional.type if conventional else None,
        conventional_scope=conventional.scope if conventional else None,
        conventional_breaking=conventional.breaking if conventional else False,
        url=commit.html_url or f"{repo_url}/commit/{commit.sha}",
    )


# --------------------------------------------------------------------------- category hints

_TYPE_TO_CATEGORY = {
    "feat": "feature",
    "fix": "fix",
    "perf": "performance",
    "docs": "docs",
    "refactor": "internal",
    "chore": "internal",
    "test": "internal",
    "build": "internal",
    "ci": "internal",
    "style": "internal",
    "deps": "internal",
    "revert": "fix",
}
# Matched as whole words against lower-cased labels ("type: bug", "kind/feature",
# "area: docs"). Whole words so "docker" is not documentation and "prefix" is not a fix.
_LABEL_HINTS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern), category)
    for pattern, category in (
        (r"\bperf(ormance)?\b", "performance"),
        (r"\b(bug|bugfix|fix|regression)\b", "fix"),
        (r"\b(feature|feat|enhancement|new)\b", "feature"),
        (r"\b(docs?|documentation)\b", "docs"),
        # Not "internal": "contributor: internal" describes the author, not the change.
        (r"\b(dependencies|deps|chore|ci|tests?|refactor)\b", "internal"),
    )
)


_TITLE_NOISE = re.compile(r"^(?:\s*(?:\[[^\]]*\]|:[a-z_]+:|[^\w\s\[]+))+\s*")


def hint_category(item: ChangeItem) -> str:
    """A deterministic category guess from labels, then the conventional type, then words.

    Used for fallback items (when the model fails or skips an input) and as the reference
    for the category-accuracy scorer. Labels win because a maintainer applied them on
    purpose; a conventional type is the author's own claim; title words are a last resort.
    """
    for label in (label.lower() for label in item.labels):
        for pattern, category in _LABEL_HINTS:
            if pattern.search(label):
                return category
    if item.conventional_type in _TYPE_TO_CATEGORY:
        return _TYPE_TO_CATEGORY[item.conventional_type]
    # "[ios][ui] Add x", ":bug: Fix y", "🐛 Fix z" -> the words that carry the meaning.
    title = _TITLE_NOISE.sub("", item.title).lower()
    if title.startswith(("fix", "bug", "resolve", "correct", "prevent", "handle")):
        return "fix"
    if title.startswith(("add", "support", "introduce", "implement", "new", "allow")):
        return "feature"
    if title.startswith(("doc", "readme")):
        return "docs"
    if title.startswith(("bump", "chore", "update dependency", "ci", "test", "refactor")):
        return "internal"
    return "internal"


def hint_breaking(item: ChangeItem) -> bool:
    return item.conventional_breaking or any("breaking" in label.lower() for label in item.labels)
