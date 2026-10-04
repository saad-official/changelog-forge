"""Code-based scorers. Each takes the pipeline's output and the hand-written expectations
and returns a number; none of them calls a model.

Why code first: these properties are *checkable*. Whether PR #123 is mentioned, whether a
link points at a commit in the range, whether a breaking change was flagged - a function
answers that exactly and for free, every CI run. An LLM judge is reserved for the one thing
code cannot judge (is the prose good?) and is reported separately (judge.py), because a
noisy 1-5 score averaged into exact metrics would hide regressions in both.
"""

from __future__ import annotations

import re
from typing import Any

from ..models import ReleaseNotes, Verification
from ..normalise import normalise
from ..pipeline.verify import LIMITS, RefIndex
from .golden import Expected

_PR_URL = re.compile(r"^https://github\.com/(?P<repo>[^/]+/[^/]+)/pull/(?P<number>\d+)$")
_COMMIT_URL = re.compile(
    r"^https://github\.com/(?P<repo>[^/]+/[^/]+)/commit/(?P<sha>[0-9a-f]{40})$"
)

# Pass/fail gates: a case fails if any of these is violated.
GATES = {
    "hallucinated_refs": lambda v: v == 0,
    "link_validity": lambda v: v == 1.0,
    "json_valid": lambda v: v == 1.0,
    "length_budget": lambda v: v == 1.0,
    "forbidden_claims": lambda v: v == 0,
}


def _canonical(index: RefIndex, ref: str) -> str | None:
    return index.resolve(ref)[0]


def _doc_refs(doc: ReleaseNotes) -> list[str]:
    return [
        ref.id if ref.kind == "pr" else (ref.sha or ref.id)
        for item in doc.all_items()
        for ref in item.refs
    ]


def coverage_recall(dev: ReleaseNotes, expected: Expected, index: RefIndex) -> float | None:
    wanted = {c for ref in expected.must_mention if (c := _canonical(index, ref))}
    if not wanted:
        return None
    present = {c for ref in _doc_refs(dev) if (c := _canonical(index, ref))}
    return len(wanted & present) / len(wanted)


def hallucinated_refs(docs: list[ReleaseNotes], index: RefIndex) -> int:
    """References in the final documents that do not exist in the input. Must be 0: the
    verifier guarantees it, and this scorer is what proves the verifier works."""
    return sum(1 for doc in docs for ref in _doc_refs(doc) if _canonical(index, ref) is None)


def _flagged(dev: ReleaseNotes, index: RefIndex) -> set[str]:
    flagged: set[str] = set()
    for item in dev.all_items():
        if item.breaking or item.possibly_breaking:
            for ref in item.refs:
                canonical = _canonical(index, ref.id if ref.kind == "pr" else ref.sha or "")
                if canonical:
                    flagged.add(canonical)
    return flagged


def breaking_scores(
    dev: ReleaseNotes, expected: Expected, index: RefIndex
) -> tuple[float | None, float | None]:
    """(recall, precision) of breaking-change detection, counting "possibly breaking"."""
    must = {c for ref in expected.must_flag_breaking if (c := _canonical(index, ref))}
    may = {c for ref in expected.may_flag_breaking if (c := _canonical(index, ref))}
    flagged = _flagged(dev, index)
    recall = len(must & flagged) / len(must) if must else None
    precision = len(flagged & (must | may)) / len(flagged) if flagged else None
    return recall, precision


def category_accuracy(dev: ReleaseNotes, expected: Expected, index: RefIndex) -> float | None:
    if not expected.categories:
        return None
    by_ref: dict[str, str] = {}
    for item in dev.all_items():
        for ref in item.refs:
            canonical = _canonical(index, ref.id if ref.kind == "pr" else ref.sha or "")
            if canonical and canonical not in by_ref:
                by_ref[canonical] = item.category
    scored = correct = 0
    for ref, category in expected.categories.items():
        canonical = _canonical(index, ref)
        if canonical is None:
            continue
        scored += 1
        correct += by_ref.get(canonical) == category
    return correct / scored if scored else None


def link_validity(docs: list[ReleaseNotes], index: RefIndex) -> float:
    total = valid = 0
    for doc in docs:
        for item in doc.all_items():
            for ref in item.refs:
                total += 1
                if ref.kind == "pr":
                    match = _PR_URL.match(ref.url)
                    ok = (
                        bool(match)
                        and match.group("repo") == doc.repo
                        and (int(match.group("number")) in index.pr_numbers)
                    )
                else:
                    match = _COMMIT_URL.match(ref.url)
                    ok = (
                        bool(match)
                        and match.group("repo") == doc.repo
                        and (match.group("sha") in index.sha_owner)
                    )
                valid += ok
    return valid / total if total else 1.0


def length_budget(docs: list[ReleaseNotes]) -> float:
    ok = True
    for doc in docs:
        ok &= len(doc.intro) <= LIMITS["intro"]
        for section in doc.sections:
            ok &= section.prose is None or len(section.prose) <= LIMITS["prose"]
            for item in section.items:
                limit = LIMITS["dev_summary"] if doc.audience == "dev" else LIMITS["user_summary"]
                ok &= len(item.summary) <= limit
                ok &= (
                    item.migration_note is None
                    or len(item.migration_note) <= LIMITS["migration_note"]
                )
    return 1.0 if ok else 0.0


def json_valid(docs: list[ReleaseNotes]) -> float:
    for doc in docs:
        try:
            ReleaseNotes.model_validate_json(doc.model_dump_json())
        except Exception:
            return 0.0
    return 1.0


def forbidden_claims(markdown: list[str], expected: Expected) -> int:
    return sum(
        1
        for pattern in expected.forbidden_claims
        for text in markdown
        if re.search(pattern, text, re.IGNORECASE)
    )


def score_case(
    *,
    collected: Any,
    outputs: dict[str, ReleaseNotes],
    markdown: dict[str, str],
    verification: Verification,
    expected: Expected,
) -> dict[str, Any]:
    items, _ = normalise(collected)
    index = RefIndex(items)
    docs = list(outputs.values())
    dev = outputs.get("dev") or docs[0]
    recall, precision = breaking_scores(dev, expected, index)
    metrics: dict[str, Any] = {
        "coverage_recall": coverage_recall(dev, expected, index),
        "hallucinated_refs": hallucinated_refs(docs, index),
        "dropped_by_verifier": len(verification.dropped_refs),
        "breaking_recall": recall,
        "breaking_precision": precision,
        "category_accuracy": category_accuracy(dev, expected, index),
        "link_validity": link_validity(docs, index),
        "length_budget": length_budget(docs),
        "json_valid": json_valid(docs),
        "forbidden_claims": forbidden_claims(list(markdown.values()), expected),
        "fallback_items": sum(1 for item in dev.all_items() if item.source == "fallback"),
        "degraded": len(verification.degraded),
    }
    metrics["passed"] = all(gate(metrics[name]) for name, gate in GATES.items())
    return metrics
