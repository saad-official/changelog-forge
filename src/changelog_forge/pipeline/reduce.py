"""Reduce: the verified item list -> per-audience editorial (intro, order, section prose).

Two calls on the capable tier, dev first, then user. The dev call also proposes duplicate
groups; those are applied once, deterministically, and the user call then receives the
already-merged list. Both documents are rendered from that same list of items, whose text
the reducer never rewrites - so the two documents can differ in tone and selection but
never in facts.

If a reduce call fails on every route, the run still completes with a deterministic draft
(template intro, input order). Degraded, recorded in `Verification.degraded`, but shipped.
"""

from __future__ import annotations

import json
from collections import Counter

from ..llm import StructuredLLM
from ..models import SECTION_TITLES, DevDraft, MergedItem, SectionDraft, UserDraft
from ..prompts import Prompt, wrap_untrusted
from .verify import audience_items, section_for


def build_reduce_message(
    repo: str, base: str, head: str, items: list[MergedItem], audience: str
) -> str:
    rows = []
    for item in audience_items(items, audience):
        section = section_for(item, audience)
        row = {
            "id": item.id,
            # "possibly_breaking" is ours, not the reducer's: it orders those under breaking.
            "section": "breaking" if section == "possibly_breaking" else section,
            "summary": item.dev_summary if audience == "dev" else item.user_summary,
        }
        if audience == "dev" and item.breaking:
            row["breaking_confidence"] = round(item.breaking_confidence, 2)
            row["migration_note"] = item.migration_note
        rows.append(row)
    payload = json.dumps(rows, ensure_ascii=False, indent=None)
    return (
        f"Repository: {repo}\nRange: {base}...{head}\nAudience: {audience}\n\n"
        f"{wrap_untrusted('release_items', payload)}"
    )


def reduce_dev(
    llm: StructuredLLM, prompt: Prompt, *, repo: str, base: str, head: str, items: list[MergedItem]
) -> DevDraft:
    return llm.complete_structured(
        build_reduce_message(repo, base, head, items, "dev"),
        DevDraft,
        system=prompt.text,
        label="reduce:dev",
    )


def reduce_user(
    llm: StructuredLLM, prompt: Prompt, *, repo: str, base: str, head: str, items: list[MergedItem]
) -> UserDraft:
    return llm.complete_structured(
        build_reduce_message(repo, base, head, items, "user"),
        UserDraft,
        system=prompt.text,
        label="reduce:user",
    )


def default_draft(items: list[MergedItem], audience: str, repo: str) -> DevDraft:
    """The no-model draft: a counted, factual intro and input order."""
    counts = Counter(section_for(item, audience) for item in audience_items(items, audience))
    parts = [
        f"{counts[key]} {SECTION_TITLES[key].lower()}"
        for key in (
            "breaking",
            "possibly_breaking",
            "feature",
            "fix",
            "performance",
            "docs",
            "internal",
        )
        if counts.get(key)
    ]
    if audience == "user":
        intro = (
            f"This release of {repo} brings "
            + (", ".join(parts) if parts else "small changes")
            + "."
        )
    else:
        intro = f"{sum(counts.values())} changes in {repo}: " + (", ".join(parts) or "none") + "."
    sections = [
        SectionDraft(section=key, prose=None, item_ids=[])  # type: ignore[arg-type]
        for key in ("breaking", "feature", "fix", "performance", "docs", "internal")
    ]
    return DevDraft(intro=intro, sections=sections, duplicates=[])
