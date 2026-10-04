"""Verify: deterministic checks between the models and the reader.

The model is trusted to *write*; it is not trusted to *cite*. Every reference it emits is
resolved against the set collected from GitHub, and anything that does not resolve is
dropped and recorded - never "corrected" by guessing. Docs/decisions/0003 explains why this
is code and not another prompt ("please double-check your references").

Checks, in pipeline order:

  map output   refs resolve (PR numbers and SHA prefixes in the collected set), every item
               keeps at least one ref, breaking_confidence clamped to [0, 1], every input
               item is covered (an input the model skipped gets a deterministic fallback
               item, so nothing silently disappears from the notes).
  reduce       item ids exist, each placed once, unplaced items appended in their section,
               duplicates only merge known ids.
  both docs    breaking needs confidence >= 0.6, else "possibly breaking" in the dev doc
               and not presented as breaking in the user doc; length budgets per field.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..models import (
    Change,
    ChangeItem,
    DevDraft,
    Downgraded,
    DroppedRef,
    MergedItem,
    Ref,
    SectionDraft,
    UserDraft,
    Verification,
)
from ..normalise import hint_breaking, hint_category

BREAKING_THRESHOLD = 0.6
USER_SECTIONS = ("breaking", "feature", "fix", "performance")
DEV_SECTIONS = (
    "breaking",
    "possibly_breaking",
    "feature",
    "fix",
    "performance",
    "docs",
    "internal",
)

# Character budgets. A summary longer than this is a paragraph pretending to be a bullet.
LIMITS = {
    "intro": 700,
    "prose": 300,
    "user_summary": 240,
    "dev_summary": 320,
    "migration_note": 400,
}

# "#123", "PR #123", "pull/123", and a bare "123": the first live smoke run showed
# gpt-oss-20b citing bare numbers for 11 of 20 items. A bare number of up to 6 digits cannot
# be a SHA prefix (those are 7+ hex chars), so it is read as a PR number - and then checked
# against the collected set like any other ref. Canonicalising is not trusting.
_PR_REF = re.compile(r"^(?:(?:#|pr\s*#?|pull/)(\d+)|(\d{1,6}))$", re.IGNORECASE)
_URL_PR = re.compile(r"/pull/(\d+)/?$")
_URL_SHA = re.compile(r"/commit/([0-9a-f]{7,40})/?$", re.IGNORECASE)
_SHA = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)


class RefIndex:
    """Every reference that exists in the collected input, and how to canonicalise one."""

    def __init__(self, items: list[ChangeItem]):
        self.items = items
        self.pr_numbers: dict[int, ChangeItem] = {
            item.pr_number: item for item in items if item.pr_number is not None
        }
        self.sha_owner: dict[str, ChangeItem] = {sha: item for item in items for sha in item.shas}

    def resolve(self, ref: str) -> tuple[str | None, str]:
        """Return (canonical ref, reason). Canonical is "#123" or a full 40-char SHA.

        A SHA that belongs to a PR is canonicalised to the PR: the PR page is the better
        link for a reader, and it makes "same change cited twice" detectable.
        """
        text = ref.strip().strip("`'\"()[]")
        url_pr, url_sha = _URL_PR.search(text), _URL_SHA.search(text)
        if url_pr:
            text = f"#{url_pr.group(1)}"
        elif url_sha:
            text = url_sha.group(1)
        pr = _PR_REF.match(text)
        if pr:
            number = int(pr.group(1) or pr.group(2))
            if number in self.pr_numbers:
                return f"#{number}", "ok"
            return None, f"PR #{number} is not in the collected range"
        if _SHA.match(text):
            matches = [sha for sha in self.sha_owner if sha.startswith(text.lower())]
            if len(matches) == 1:
                owner = self.sha_owner[matches[0]]
                if owner.pr_number is not None:
                    return f"#{owner.pr_number}", "ok"
                return matches[0], "ok"
            if len(matches) > 1:
                return None, f"SHA prefix {text} is ambiguous"
            return None, f"commit {text} is not in the collected range"
        return None, f"{ref!r} is not a PR number or commit SHA"

    def item_for(self, canonical: str) -> ChangeItem | None:
        if canonical.startswith("#"):
            return self.pr_numbers.get(int(canonical[1:]))
        return self.sha_owner.get(canonical)

    def canonical_refs(self, item: ChangeItem) -> list[str]:
        return [f"#{item.pr_number}"] if item.pr_number is not None else list(item.shas)


def trim(text: str, limit: int) -> str:
    """Cut at a word boundary and mark the cut; never mid-word, never silently."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:-")
    return cut + "…"


def _budget(text: str | None, field: str, where: str, verification: Verification) -> str | None:
    if text is None:
        return None
    limit = LIMITS[field]
    cleaned = " ".join(text.split())
    if len(cleaned) > limit:
        verification.trimmed.append(f"{where}.{field}")
        return trim(cleaned, limit)
    return cleaned


def fallback_item(item: ChangeItem, index: RefIndex) -> MergedItem:
    """A deterministic item for an input the model skipped or could not process.

    Plain, a little dull, and true: the PR title, categorised from labels and the
    conventional type. Better than dropping the change from the notes.
    """
    title = item.title.rstrip(".")
    if sum(ch.isalnum() for ch in title) < 3:  # a commit titled "+" says nothing
        title = f"Maintenance commit {item.shas[0][:7]}"
    breaking = hint_breaking(item)
    return MergedItem(
        id="",
        category=hint_category(item),  # type: ignore[arg-type]
        user_summary=title,
        dev_summary=title,
        breaking=breaking,
        breaking_confidence=0.9 if breaking else 0.0,
        migration_note=None,
        refs=index.canonical_refs(item),
        source="fallback",
    )


def verify_changes(
    changes: Iterable[Change], items: list[ChangeItem], verification: Verification
) -> list[MergedItem]:
    """Map output -> the verified, deduplicated, fully-covering list of MergedItems."""
    index = RefIndex(items)
    merged: list[MergedItem] = []
    by_refs: dict[tuple[str, ...], MergedItem] = {}

    for number, change in enumerate(changes, start=1):
        label = f"change {number} ({change.dev_summary[:60]!r})"
        refs: list[str] = []
        for ref in change.refs:
            verification.checked_refs += 1
            canonical, reason = index.resolve(ref)
            if canonical is None:
                verification.dropped_refs.append(DroppedRef(ref=ref, stage="map", reason=reason))
            elif canonical not in refs:
                refs.append(canonical)
        if not refs:
            verification.dropped_items.append(label)
            continue
        confidence = change.breaking_confidence
        if not 0.0 <= confidence <= 1.0:
            verification.clamped.append(f"{label}: breaking_confidence {confidence}")
            confidence = min(1.0, max(0.0, confidence))
        candidate = MergedItem(
            id="",
            category=change.category,
            user_summary=change.user_summary,
            dev_summary=change.dev_summary,
            breaking=change.breaking,
            breaking_confidence=confidence if change.breaking else 0.0,
            migration_note=change.migration_note or None,
            refs=refs,
        )
        key = tuple(sorted(refs))
        if key in by_refs:  # the same change emitted twice: keep the first, merge the flags
            _absorb(by_refs[key], candidate)
            continue
        by_refs[key] = candidate
        merged.append(candidate)

    cited = {ref for item in merged for ref in item.refs}
    for item in items:
        if not any(ref in cited for ref in index.canonical_refs(item)):
            verification.uncovered_inputs.append(item.id)
            merged.append(fallback_item(item, index))

    for position, item in enumerate(merged, start=1):
        item.id = f"i{position}"
    return merged


def _absorb(keep: MergedItem, other: MergedItem) -> None:
    for ref in other.refs:
        if ref not in keep.refs:
            keep.refs.append(ref)
    if other.breaking and other.breaking_confidence > keep.breaking_confidence:
        keep.breaking = True
        keep.breaking_confidence = other.breaking_confidence
    keep.migration_note = keep.migration_note or other.migration_note


def apply_duplicates(
    items: list[MergedItem], draft: DevDraft, verification: Verification
) -> list[MergedItem]:
    """Merge the duplicate groups the dev reducer proposed - known ids only, each once."""
    by_id = {item.id: item for item in items}
    absorbed: set[str] = set()
    for group in draft.duplicates:
        if group.keep not in by_id or group.keep in absorbed:
            verification.unknown_item_ids.append(group.keep)
            continue
        for other_id in group.merge:
            if other_id not in by_id or other_id == group.keep or other_id in absorbed:
                if other_id not in by_id:
                    verification.unknown_item_ids.append(other_id)
                continue
            _absorb(by_id[group.keep], by_id[other_id])
            absorbed.add(other_id)
    return [item for item in items if item.id not in absorbed]


def is_confirmed_breaking(item: MergedItem) -> bool:
    return item.breaking and item.breaking_confidence >= BREAKING_THRESHOLD


def is_possibly_breaking(item: MergedItem) -> bool:
    return item.breaking and item.breaking_confidence < BREAKING_THRESHOLD


def make_ref(repo: str, canonical: str) -> Ref:
    """A canonical ref ("#123" or a full SHA) as a link object for the documents."""
    if canonical.startswith("#"):
        number = int(canonical[1:])
        return Ref(
            kind="pr", id=canonical, url=f"https://github.com/{repo}/pull/{number}", number=number
        )
    return Ref(
        kind="commit",
        id=canonical[:7],
        url=f"https://github.com/{repo}/commit/{canonical}",
        sha=canonical,
    )


def record_downgrades(items: list[MergedItem], verification: Verification, repo: str) -> None:
    for item in items:
        if is_possibly_breaking(item):
            verification.downgraded.append(
                Downgraded(
                    item_id=item.id,
                    summary=item.dev_summary,
                    refs=[make_ref(repo, ref) for ref in item.refs],
                    breaking_confidence=round(item.breaking_confidence, 2),
                    reason=(
                        f"breaking confidence {item.breaking_confidence:.2f} is below "
                        f"{BREAKING_THRESHOLD}: shown as possibly breaking to developers, "
                        "not as breaking to users"
                    ),
                )
            )


def section_for(item: MergedItem, audience: str) -> str | None:
    """Which section an item belongs in. Decided here, from the item's own (verified) facts,
    never by the reducer: the reducer orders and introduces sections, it does not move
    items between them."""
    if is_confirmed_breaking(item):
        return "breaking"
    if audience == "dev":
        return "possibly_breaking" if is_possibly_breaking(item) else item.category
    return item.category if item.category in USER_SECTIONS else None


def audience_items(items: list[MergedItem], audience: str) -> list[MergedItem]:
    return [item for item in items if section_for(item, audience) is not None]


def plan_sections(
    items: list[MergedItem],
    draft: DevDraft | UserDraft,
    audience: str,
    verification: Verification,
) -> list[tuple[str, str | None, list[MergedItem]]]:
    """Combine the reducer's ordering and prose with the verified placement.

    Returns [(section key, prose, items)] in canonical section order, empty sections
    omitted. Ids the reducer invented are recorded and ignored; items it forgot are
    appended to their section in input order, so the document is always complete.
    """
    order = DEV_SECTIONS if audience == "dev" else USER_SECTIONS
    by_id = {item.id: item for item in audience_items(items, audience)}
    placed: dict[str, list[MergedItem]] = {key: [] for key in order}
    prose: dict[str, str | None] = {}
    seen: set[str] = set()
    drafts: list[SectionDraft] = list(draft.sections)
    for section in drafts:
        if section.prose and section.section not in prose:
            prose[section.section] = _budget(
                section.prose, "prose", f"{audience}.{section.section}", verification
            )
        for item_id in section.item_ids:
            item = by_id.get(item_id)
            if item is None:
                if item_id not in seen:
                    verification.unknown_item_ids.append(f"{audience}:{item_id}")
                continue
            if item_id in seen:
                continue
            seen.add(item_id)
            placed[section_for(item, audience) or item.category].append(item)
    for item in by_id.values():
        if item.id not in seen:
            placed[section_for(item, audience) or item.category].append(item)
    return [(key, prose.get(key), placed[key]) for key in order if placed[key]]


def enforce_item_budgets(items: list[MergedItem], verification: Verification) -> None:
    for item in items:
        item.user_summary = _budget(item.user_summary, "user_summary", item.id, verification) or ""
        item.dev_summary = _budget(item.dev_summary, "dev_summary", item.id, verification) or ""
        item.migration_note = _budget(item.migration_note, "migration_note", item.id, verification)


def budget_intro(text: str, audience: str, verification: Verification) -> str:
    return _budget(text, "intro", audience, verification) or ""
