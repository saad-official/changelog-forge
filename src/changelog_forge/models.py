"""Every data shape that crosses a boundary, as a Pydantic model.

Three families, in pipeline order:

  input     CommitRecord / CollectedRange (what GitHub said) -> ChangeItem (normalised)
  model     Change / GroupAnalysis (map output), DevDraft / UserDraft (reduce output).
            These are sent to providers as strict JSON Schemas, so every field is REQUIRED
            and optionality is expressed as a nullable type (`str | None`) rather than a
            default. Groq/OpenAI strict mode has no way to say "this key may be absent",
            and llm-kit's `require_all_properties` makes every key required anyway, so the
            model and the schema agree up front. No numeric `ge`/`le` constraints either:
            strict-mode grammars reject `minimum`/`maximum` on some providers, so ranges
            are clamped by the verifier instead (a deterministic step we can test).
  output    ReleaseNotes (rendered document as data), Verification, Usage, RunEvent.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Category = Literal["feature", "fix", "performance", "docs", "internal"]
SectionKey = Literal["breaking", "feature", "fix", "performance", "docs", "internal"]
Audience = Literal["user", "dev"]
RunStatus = Literal["queued", "collecting", "mapping", "reducing", "verifying", "done", "failed"]

CATEGORIES: tuple[Category, ...] = ("feature", "fix", "performance", "docs", "internal")
AUDIENCES: tuple[Audience, ...] = ("user", "dev")
SECTION_TITLES: dict[str, str] = {
    "breaking": "Breaking changes",
    "possibly_breaking": "Possibly breaking",
    "feature": "Features",
    "fix": "Fixes",
    "performance": "Performance",
    "docs": "Docs",
    "internal": "Internal",
}
TERMINAL_STATUSES: frozenset[str] = frozenset({"done", "failed"})


def utcnow() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------- input


class CommitRecord(BaseModel):
    """One commit as collected from GitHub, enriched with its pull request.

    This is also the row shape of the `(repo, sha)` cache: a commit is immutable, so once
    its PR association is known there is no reason to ask GitHub again.
    """

    sha: str
    message: str
    author: str | None = None
    date: datetime | None = None
    parents: int = 1
    html_url: str = ""
    pr_number: int | None = None
    pr_title: str | None = None
    pr_body: str | None = None
    pr_url: str | None = None
    labels: list[str] = Field(default_factory=list)
    # None means "not fetched" (unauthenticated runs skip per-commit file lists to save
    # rate limit), which is different from "touched no files".
    files: list[str] | None = None

    @property
    def subject(self) -> str:
        return self.message.split("\n", 1)[0].strip()


class CollectedRange(BaseModel):
    """Everything `collect` produced for one `base..head` range. Snapshotted for evals."""

    repo: str  # "owner/name"
    base: str
    head: str
    compare_url: str
    default_branch: str | None = None
    private: bool = False
    total_commits: int
    commits: list[CommitRecord]
    collected_at: datetime = Field(default_factory=utcnow)
    api_calls: int = 0
    cache_hits: int = 0


class ChangeItem(BaseModel):
    """One logical change: a pull request (with all of its commits) or a lone commit."""

    id: str  # "pr-123" or "c-<sha7>"
    kind: Literal["pr", "commit"]
    pr_number: int | None = None
    title: str
    body: str = ""
    shas: list[str]
    authors: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    conventional_type: str | None = None
    conventional_scope: str | None = None
    conventional_breaking: bool = False
    url: str = ""

    @property
    def refs(self) -> list[str]:
        """The references a model may cite for this item."""
        refs = [f"#{self.pr_number}"] if self.pr_number is not None else []
        return refs + [sha[:7] for sha in self.shas]


# --------------------------------------------------------------------------- model I/O


class Change(BaseModel):
    """One release-note item, as the map model produces it."""

    category: Category
    user_summary: str = Field(description="One sentence for end users, no jargon.")
    dev_summary: str = Field(description="One sentence for developers, precise.")
    breaking: bool
    breaking_confidence: float = Field(description="0 to 1: how sure you are it is breaking.")
    migration_note: str | None = Field(description="What a user must change, or null.")
    refs: list[str] = Field(description='Only refs from the input: "#123" or a commit SHA.')


class GroupAnalysis(BaseModel):
    changes: list[Change]


class SectionDraft(BaseModel):
    section: SectionKey
    prose: str | None = Field(description="One or two sentences introducing the section, or null.")
    item_ids: list[str] = Field(description="Item ids from the input, most important first.")


class DuplicateGroup(BaseModel):
    keep: str = Field(description="The item id to keep.")
    merge: list[str] = Field(description="Item ids describing the same change as `keep`.")


class DevDraft(BaseModel):
    intro: str
    sections: list[SectionDraft]
    duplicates: list[DuplicateGroup]


class UserDraft(BaseModel):
    intro: str
    sections: list[SectionDraft]


class MergedItem(BaseModel):
    """A verified change after map, ref verification and dedupe: the shared fact list.

    Both audience documents are rendered from the same list of these, which is why the
    user notes and the developer notes cannot disagree about what changed.
    """

    id: str  # "i1", "i2", ... stable within a run
    category: Category
    user_summary: str
    dev_summary: str
    breaking: bool
    breaking_confidence: float
    migration_note: str | None = None
    refs: list[str]  # canonical: "#123" or a full 40-char SHA
    source: Literal["model", "fallback"] = "model"


# --------------------------------------------------------------------------- output


class Ref(BaseModel):
    kind: Literal["pr", "commit"]
    id: str  # display form: "#123" or "abc1234"
    url: str
    number: int | None = None
    sha: str | None = None


class NoteItem(BaseModel):
    id: str
    category: Category
    summary: str
    breaking: bool = False
    possibly_breaking: bool = False
    breaking_confidence: float = 0.0
    migration_note: str | None = None
    refs: list[Ref]
    source: Literal["model", "fallback"] = "model"


class Section(BaseModel):
    category: str  # a SectionKey, or "possibly_breaking" in the dev document
    title: str
    prose: str | None = None
    items: list[NoteItem]


class ReleaseNotes(BaseModel):
    """One audience's document as data. The Markdown is rendered from exactly this."""

    schema_version: Literal["1"] = "1"
    audience: Audience
    repo: str
    base: str
    head: str
    title: str
    intro: str
    sections: list[Section]
    compare_url: str
    commit_count: int
    generated_at: datetime = Field(default_factory=utcnow)
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    models: dict[str, str] = Field(default_factory=dict)

    def all_items(self) -> list[NoteItem]:
        return [item for section in self.sections for item in section.items]


class DroppedRef(BaseModel):
    ref: str
    stage: Literal["map", "reduce"]
    reason: str


class Downgraded(BaseModel):
    """A breaking claim below the confidence threshold: "possibly breaking" in the dev
    document, not presented as breaking in the user document."""

    item_id: str
    summary: str
    refs: list[Ref]
    breaking_confidence: float
    reason: str


class Verification(BaseModel):
    """What the deterministic verifier changed, so nothing is silently corrected."""

    checked_refs: int = 0
    dropped_refs: list[DroppedRef] = Field(default_factory=list)
    dropped_items: list[str] = Field(default_factory=list)
    downgraded: list[Downgraded] = Field(default_factory=list)
    uncovered_inputs: list[str] = Field(default_factory=list)
    unknown_item_ids: list[str] = Field(default_factory=list)
    trimmed: list[str] = Field(default_factory=list)
    clamped: list[str] = Field(default_factory=list)
    degraded: list[str] = Field(default_factory=list)


class ModelUsage(BaseModel):
    model: str
    provider: str = ""
    stage: str = ""  # "map", "reduce", "judge"
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    usd: float = 0.0


class Usage(BaseModel):
    """The run's ledger, summarised for the UI and the `runs.usage` column."""

    calls: int = 0
    failed_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    usd: float = 0.0
    max_usd: float | None = None
    by_model: list[ModelUsage] = Field(default_factory=list)
    summary: str = ""
    prices_verified_on: str = ""

    @classmethod
    def from_ledger(cls, ledger: Any, max_usd: float | None = None) -> Usage:
        from llm_kit import PRICES_VERIFIED_ON

        rows: dict[tuple[str, str], ModelUsage] = {}
        for record in ledger.records:
            stage = record.label.split(":", 1)[0]
            row = rows.setdefault(
                (record.model, stage),
                ModelUsage(model=record.model, provider=record.provider, stage=stage),
            )
            row.calls += 1
            row.prompt_tokens += record.usage.prompt_tokens
            row.completion_tokens += record.usage.completion_tokens
            row.reasoning_tokens += record.usage.reasoning_tokens
            row.usd = round(row.usd + record.cost_usd, 8)
        total = ledger.total_usage
        return cls(
            calls=len(ledger.records),
            failed_calls=sum(1 for record in ledger.records if record.error),
            prompt_tokens=total.prompt_tokens,
            completion_tokens=total.completion_tokens,
            reasoning_tokens=total.reasoning_tokens,
            total_tokens=total.total_tokens,
            usd=round(ledger.total_usd, 8),
            max_usd=max_usd,
            by_model=list(rows.values()),
            summary=ledger.summary(),
            prices_verified_on=PRICES_VERIFIED_ON,
        )


class RunEvent(BaseModel):
    run_id: str
    seq: int
    at: datetime = Field(default_factory=utcnow)
    kind: str  # status | progress | warning | done | failed
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
