"""The orchestrator: collected input -> two verified documents, resumable per stage.

    normalise -> chunk -> map (per group) -> verify refs -> reduce dev -> dedupe ->
    reduce user -> verify budgets -> render

Every model-dependent stage writes a checkpoint (`map:3`, `reduce:dev`, ...), together with
the ledger so far. A re-run of the same run - after a serverless request hit its time limit,
or a worker died - loads the checkpoints, skips finished work, and keeps counting cost from
where it stopped. `Checkpoints` is a dict-like interface so the CLI can run with a plain
dict and the API with the Store.

Failure policy (docs/architecture.md, "Failure modes"):
  - a map group whose every route fails -> deterministic fallback items for that group;
  - the ledger budget runs out mid-map -> fallback items for the remaining groups;
  - a reduce call fails -> deterministic draft (template intro, input order);
  - the request's time budget runs out -> `PipelineSuspended`, resume later.
All of these are recorded in `Verification.degraded` and as `warning` events.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from llm_kit import CallRecord, Ledger, LLMBudgetError, LLMError
from llm_kit import Usage as LLMUsage

from ..chunk import TokenCounter, chunk_items, default_counter
from ..models import (
    ChangeItem,
    CollectedRange,
    DevDraft,
    GroupAnalysis,
    MergedItem,
    ReleaseNotes,
    Usage,
    UserDraft,
    Verification,
)
from ..normalise import normalise
from ..prompts import Prompt, load_prompt
from .map import map_group
from .reduce import default_draft, reduce_dev, reduce_user
from .render import build_notes, render_markdown
from .verify import (
    RefIndex,
    apply_duplicates,
    audience_items,
    enforce_item_budgets,
    fallback_item,
    record_downgrades,
    verify_changes,
)

Emit = Callable[[str, str, dict[str, Any]], None]
OnStatus = Callable[[str], None]


class Checkpoints(Protocol):
    def get(self, key: str) -> Any: ...
    def put(self, key: str, data: Any) -> None: ...


class DictCheckpoints:
    def __init__(self, initial: dict[str, Any] | None = None):
        self.data: dict[str, Any] = dict(initial or {})

    def get(self, key: str) -> Any:
        return self.data.get(key)

    def put(self, key: str, data: Any) -> None:
        self.data[key] = data


class PipelineSuspended(Exception):
    """The time budget ran out at a stage boundary. Checkpoints are saved; call again."""


@dataclass
class PipelineResult:
    outputs: dict[str, ReleaseNotes]
    markdown: dict[str, str]
    verification: Verification
    usage: Usage
    items: list[MergedItem]
    group_count: int
    commit_count: int
    prompt_versions: dict[str, str]
    models: dict[str, str]
    skipped_shas: list[str] = field(default_factory=list)


def ledger_to_json(ledger: Ledger) -> list[dict[str, Any]]:
    return [record.as_dict() for record in ledger.records]


def ledger_from_json(rows: list[dict[str, Any]] | None, max_usd: float | None) -> Ledger:
    """Rebuild a Ledger from checkpointed records so a resumed run keeps its spend."""
    ledger = Ledger(max_usd=max_usd)
    for row in rows or []:
        ledger.add(
            CallRecord(
                provider=row["provider"],
                model=row["model"],
                label=row["label"],
                usage=LLMUsage(
                    row.get("prompt_tokens", 0),
                    row.get("completion_tokens", 0),
                    row.get("reasoning_tokens", 0),
                ),
                latency_s=row.get("latency_s", 0.0),
                finish_reason=row.get("finish_reason"),
                attempts=row.get("attempts", 1),
                error=row.get("error"),
                started_at=row.get("started_at", ""),
            )
        )
    return ledger


@dataclass
class Pipeline:
    map_llm: Any  # StructuredLLM
    reduce_llm: Any  # StructuredLLM
    ledger: Ledger
    checkpoints: Checkpoints = field(default_factory=DictCheckpoints)
    emit: Emit = lambda kind, message, data: None
    on_status: OnStatus = lambda status: None
    counter: TokenCounter | None = None
    target_tokens: int = 4500
    prompt_versions: dict[str, str] = field(
        default_factory=lambda: {"map": "v1", "reduce_user": "v1", "reduce_dev": "v1"}
    )
    deadline: float | None = None  # time.monotonic() value after which to suspend
    budget_usd: float | None = None
    clock: Callable[[], float] = time.monotonic

    def _prompt(self, name: str) -> Prompt:
        return load_prompt(name, self.prompt_versions.get(name, "v1"))

    def _check_time(self, stage: str) -> None:
        if self.deadline is not None and self.clock() >= self.deadline:
            self.checkpoints.put("ledger", ledger_to_json(self.ledger))
            raise PipelineSuspended(f"time budget reached before {stage}")

    def _save(self, key: str, data: Any) -> None:
        self.checkpoints.put(key, data)
        self.checkpoints.put("ledger", ledger_to_json(self.ledger))

    def _models(self) -> dict[str, str]:
        models: dict[str, str] = {}
        for name, llm in (("map", self.map_llm), ("reduce", self.reduce_llm)):
            served = list(dict.fromkeys(getattr(llm, "served_by", []) or []))
            cached = self.checkpoints.get(f"models:{name}") or []
            served = list(dict.fromkeys([*cached, *served]))
            if served:
                self.checkpoints.put(f"models:{name}", served)
                models[name] = ", ".join(served)
        return models

    # ------------------------------------------------------------------ stages

    def _groups(self, items: list[ChangeItem]) -> list[list[ChangeItem]]:
        """Group composition is checkpointed: a resumed run on another machine (maybe with
        a different token counter available) must see the same groups as the first attempt,
        or the `map:N` checkpoints would describe different items."""
        by_id = {item.id: item for item in items}
        saved = self.checkpoints.get("groups")
        if saved and all(item_id in by_id for group in saved for item_id in group):
            return [[by_id[item_id] for item_id in group] for group in saved]
        groups = chunk_items(
            items, target_tokens=self.target_tokens, counter=self.counter or default_counter()
        )
        self.checkpoints.put("groups", [[item.id for item in group] for group in groups])
        return groups

    def _map(
        self, collected: CollectedRange, groups: list[list[ChangeItem]], verification: Verification
    ) -> list[Any]:
        prompt = self._prompt("map")
        changes: list[Any] = []
        budget_gone = False
        for index, group in enumerate(groups, start=1):
            key = f"map:{index}"
            saved = self.checkpoints.get(key)
            if saved is not None:
                analysis = GroupAnalysis.model_validate(saved["analysis"])
                verification.degraded.extend(saved.get("degraded", []))
                changes.extend(analysis.changes)
                continue
            self._check_time(f"map group {index}")
            self.emit(
                "progress",
                f"Drafting group {index} of {len(groups)} ({len(group)} changes)",
                {
                    "stage": "mapping",
                    "group": index,
                    "groups": len(groups),
                    "group_count": len(groups),
                    "commit_count": len(collected.commits),
                    "current": index,
                    "total": len(groups),
                },
            )
            degraded: list[str] = []
            analysis = GroupAnalysis(changes=[])
            if not budget_gone:
                try:
                    analysis = map_group(
                        self.map_llm,
                        prompt,
                        repo=collected.repo,
                        base=collected.base,
                        head=collected.head,
                        group=group,
                        index=index,
                    )
                except LLMBudgetError as exc:
                    budget_gone = True
                    degraded.append(f"map group {index}: budget exhausted ({exc})")
                except LLMError as exc:
                    degraded.append(f"map group {index}: {type(exc).__name__}: {str(exc)[:300]}")
            else:
                degraded.append(f"map group {index}: skipped, budget exhausted")
            if degraded:
                # The verifier's coverage check turns every uncovered input in this group
                # into a fallback item, so an empty analysis still yields complete notes.
                self.emit("warning", degraded[-1], {"stage": "mapping", "group": index})
                verification.degraded.extend(degraded)
            self._save(key, {"analysis": analysis.model_dump(mode="json"), "degraded": degraded})
            changes.extend(analysis.changes)
        return changes

    def _reduce(
        self,
        collected: CollectedRange,
        items: list[MergedItem],
        audience: str,
        verification: Verification,
    ) -> DevDraft | UserDraft:
        key = f"reduce:{audience}"
        saved = self.checkpoints.get(key)
        model = DevDraft if audience == "dev" else UserDraft
        if saved is not None:
            verification.degraded.extend(saved.get("degraded", []))
            return model.model_validate(saved["draft"])
        if not audience_items(items, audience):
            draft: DevDraft | UserDraft = default_draft(items, audience, collected.repo)
            self._save(key, {"draft": draft.model_dump(mode="json"), "degraded": []})
            return draft
        self._check_time(f"reduce {audience}")
        self.emit(
            "progress",
            f"Merging into {'developer' if audience == 'dev' else 'user'} notes",
            {"stage": "reducing", "audience": audience},
        )
        degraded: list[str] = []
        call = reduce_dev if audience == "dev" else reduce_user
        try:
            draft = call(
                self.reduce_llm,
                self._prompt(f"reduce_{audience}"),
                repo=collected.repo,
                base=collected.base,
                head=collected.head,
                items=items,
            )
        except LLMError as exc:
            degraded.append(f"reduce {audience}: {type(exc).__name__}: {str(exc)[:300]}")
            self.emit("warning", degraded[-1], {"stage": "reducing", "audience": audience})
            verification.degraded.extend(degraded)
            draft = default_draft(items, audience, collected.repo)
            if audience == "user":
                draft = UserDraft(intro=draft.intro, sections=draft.sections)
        self._save(key, {"draft": draft.model_dump(mode="json"), "degraded": degraded})
        return draft

    # ------------------------------------------------------------------ entry point

    def run(self, collected: CollectedRange, audiences: list[str]) -> PipelineResult:
        verification = Verification()
        self.on_status("mapping")
        items, skipped = normalise(collected)
        groups = self._groups(items)
        self.emit(
            "progress",
            f"Grouped {len(collected.commits)} commits into {len(items)} changes "
            f"in {len(groups)} group{'s' if len(groups) != 1 else ''}",
            {
                "stage": "grouping",
                "commits": len(collected.commits),
                "changes": len(items),
                "groups": len(groups),
                "group_count": len(groups),
                "commit_count": len(collected.commits),
                "skipped": len(skipped),
            },
        )
        changes = self._map(collected, groups, verification)

        self.on_status("reducing")
        merged = verify_changes(changes, items, verification)
        if verification.dropped_refs:
            self.emit(
                "warning",
                f"Dropped {len(verification.dropped_refs)} reference(s) not in this range",
                {"stage": "verifying", "dropped_refs": len(verification.dropped_refs)},
            )
        dev_draft = self._reduce(collected, merged, "dev", verification)
        merged = apply_duplicates(merged, dev_draft, verification)  # type: ignore[arg-type]
        user_draft = (
            self._reduce(collected, merged, "user", verification) if "user" in audiences else None
        )

        self.on_status("verifying")
        self.emit("progress", "Verifying references and rendering", {"stage": "verifying"})
        enforce_item_budgets(merged, verification)
        record_downgrades(merged, verification, collected.repo)
        prompt_versions = {
            name: self._prompt(name).id for name in ("map", "reduce_dev", "reduce_user")
        }
        models = self._models()
        outputs: dict[str, ReleaseNotes] = {}
        markdown: dict[str, str] = {}
        for audience in audiences:
            draft = dev_draft if audience == "dev" else user_draft
            assert draft is not None
            notes = build_notes(
                audience=audience,
                items=merged,
                draft=draft,
                collected=collected,
                verification=verification,
                prompt_versions=prompt_versions,
                models=models,
            )
            outputs[audience] = notes
            markdown[audience] = render_markdown(notes)
        self.checkpoints.put("ledger", ledger_to_json(self.ledger))
        return PipelineResult(
            outputs=outputs,
            markdown=markdown,
            verification=verification,
            usage=Usage.from_ledger(self.ledger, self.budget_usd),
            items=merged,
            group_count=len(groups),
            commit_count=len(collected.commits),
            prompt_versions=prompt_versions,
            models=models,
            skipped_shas=skipped,
        )


__all__ = [
    "Checkpoints",
    "DictCheckpoints",
    "Pipeline",
    "PipelineResult",
    "PipelineSuspended",
    "RefIndex",
    "fallback_item",
    "ledger_from_json",
    "ledger_to_json",
]
