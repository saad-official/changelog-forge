"""Run lifecycle on top of the Store: create (collect) -> process (resumable) -> view.

State machine (docs/architecture.md):

    queued --process--> mapping -> reducing -> verifying -> done
       |                   \\___________ any stage ________/
       |                              |  time budget hit: lease released, status kept,
       |                              |  next /process resumes from checkpoints
       +--collect error--> failed     +--unexpected error / attempts exhausted--> failed

`collecting` happens inside `create_run`, synchronously, so a bad repo, bad range, private
repo without a token, or a rate limit is an immediate 4xx on POST instead of a run that
fails a second later. The collected input is checkpointed with the run, which is also why
a per-run GitHub token never needs to be stored: `/process` never calls GitHub.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from .collect.github import GitHubError
from .collect.refs import RangeSpec
from .db import RunRecord, Store
from .engine import Engine
from .models import AUDIENCES, CollectedRange, Usage, utcnow
from .pipeline import Pipeline, PipelineSuspended
from .pipeline.run import ledger_from_json

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
DEFAULT_TIME_BUDGET_S = 240.0


class StoreCheckpoints:
    def __init__(self, store: Store, run_id: str):
        self.store = store
        self.run_id = run_id
        self._cache = store.get_checkpoints(run_id)

    def get(self, key: str) -> Any:
        return self._cache.get(key)

    def put(self, key: str, data: Any) -> None:
        self._cache[key] = data
        self.store.put_checkpoint(self.run_id, key, data)


@dataclass
class ProcessOutcome:
    run_id: str
    status: str
    resumable: bool = False
    message: str = ""


class RunService:
    def __init__(self, engine: Engine):
        self.engine = engine
        self.store = engine.store

    def _event(self, run_id: str, kind: str, message: str, data: dict[str, Any] | None = None):
        # Every event carries a level (the UI colours log lines by it); "warn" and "error"
        # for degraded stages and failures, "info" otherwise.
        payload = {
            "level": {"warning": "warn", "failed": "error"}.get(kind, "info"),
            **(data or {}),
        }
        try:
            self.store.append_event(run_id, kind, message, payload)
        except Exception:
            log.exception("could not append event to run %s", run_id)

    # ------------------------------------------------------------------ create

    def create_run(
        self,
        spec: RangeSpec,
        audiences: list[str],
        *,
        github_token: str | None = None,
        client_key: str | None = None,
    ) -> RunRecord:
        """Create the run and collect its input. Raises GitHubError (run marked failed)."""
        ordered = [audience for audience in AUDIENCES if audience in audiences] or list(AUDIENCES)
        run = self.store.create_run(
            RunRecord(
                repo=spec.repo,
                base=spec.base,
                head=spec.head,
                status="collecting",
                audiences=ordered,
                client_key=client_key,
                routing=self.engine.routing.summary(),
                prompt_versions=dict(self.engine.routing.prompts),
            )
        )
        self._event(
            run.id,
            "status",
            f"Collecting {spec.repo} {spec.base}...{spec.head}",
            {"status": "collecting"},
        )
        github = self.engine.github_builder(github_token)
        try:
            collected = github.collect(
                spec,
                on_progress=lambda stage, current, total: (
                    self._event(
                        run.id,
                        "progress",
                        f"Looked up {current} of {total} commits",
                        {"stage": stage, "current": current, "total": total},
                    )
                    if current
                    else None
                ),
            )
        except GitHubError as exc:
            self.store.update_run(run.id, status="failed", error=exc.message, finished_at=utcnow())
            self._event(run.id, "failed", exc.message, {"status": "failed"})
            raise
        finally:
            github.close()
        self.store.put_checkpoint(run.id, "collected", collected.model_dump(mode="json"))
        self.store.update_run(run.id, status="queued", commit_count=len(collected.commits))
        self._event(
            run.id,
            "status",
            f"Collected {len(collected.commits)} commits "
            f"({collected.api_calls} GitHub calls, {collected.cache_hits} cached)",
            {
                "status": "queued",
                "commits": len(collected.commits),
                "commit_count": len(collected.commits),
                "api_calls": collected.api_calls,
                "cache_hits": collected.cache_hits,
            },
        )
        return self.store.get_run(run.id) or run

    # ------------------------------------------------------------------ process

    def process(self, run_id: str, time_budget_s: float | None = None) -> ProcessOutcome:
        """Run (or resume) the pipeline for a queued run. Idempotent and safe to race."""
        budget = time_budget_s or DEFAULT_TIME_BUDGET_S
        claimed = self.store.claim_run(run_id, lease_s=budget + 30, max_attempts=MAX_ATTEMPTS)
        if claimed is None:
            run = self.store.get_run(run_id)
            if run is None:
                return ProcessOutcome(run_id, "missing", message="run not found")
            if run.status in ("done", "failed"):
                return ProcessOutcome(run_id, run.status, message="already finished")
            if run.attempts >= MAX_ATTEMPTS:
                message = f"gave up after {run.attempts} attempts"
                self.store.update_run(run_id, status="failed", error=message, finished_at=utcnow())
                self._event(run_id, "failed", message, {"status": "failed"})
                return ProcessOutcome(run_id, "failed", message=message)
            return ProcessOutcome(run_id, "in_progress", message="already being processed")

        checkpoints = StoreCheckpoints(self.store, run_id)
        collected_raw = checkpoints.get("collected")
        if collected_raw is None:
            message = "run has no collected input"
            self.store.update_run(run_id, status="failed", error=message, finished_at=utcnow())
            self._event(run_id, "failed", message, {"status": "failed"})
            return ProcessOutcome(run_id, "failed", message=message)
        collected = CollectedRange.model_validate(collected_raw)

        budget_usd = self.engine.budget_usd
        ledger = ledger_from_json(checkpoints.get("ledger"), budget_usd)
        map_llm, reduce_llm = self.engine.llm_builder(ledger)

        def on_status(status: str) -> None:
            self.store.update_run(run_id, status=status)
            self._event(run_id, "status", status.capitalize(), {"status": status})

        pipeline = Pipeline(
            map_llm=map_llm,
            reduce_llm=reduce_llm,
            ledger=ledger,
            checkpoints=checkpoints,
            emit=lambda kind, message, data: self._event(run_id, kind, message, data),
            on_status=on_status,
            counter=self.engine.counter,
            prompt_versions=dict(self.engine.routing.prompts),
            target_tokens=self.engine.routing.chunk.target_tokens,
            deadline=time.monotonic() + budget,
            budget_usd=budget_usd,
        )
        try:
            result = pipeline.run(collected, claimed.audiences)
        except PipelineSuspended as exc:
            # Not a failure: give the attempt back and release the lease for the next call.
            self.store.update_run(
                run_id,
                attempts=max(0, claimed.attempts - 1),
                lease_until=None,
                usage=Usage.from_ledger(ledger, budget_usd).model_dump(mode="json"),
            )
            self._event(
                run_id,
                "progress",
                f"Paused ({exc}); resuming on the next call",
                {"stage": "suspended", "resumable": True},
            )
            return ProcessOutcome(run_id, "queued", resumable=True, message=str(exc))
        except Exception as exc:
            log.exception("run %s failed", run_id)
            message = f"{type(exc).__name__}: {exc}"[:1000]
            self.store.update_run(
                run_id,
                status="failed",
                error=message,
                lease_until=None,
                finished_at=utcnow(),
                usage=Usage.from_ledger(ledger, budget_usd).model_dump(mode="json"),
            )
            self._event(run_id, "failed", message, {"status": "failed"})
            return ProcessOutcome(run_id, "failed", message=message)

        verified = result.verification.model_dump(mode="json")
        for audience, notes in result.outputs.items():
            self.store.put_output(
                run_id, audience, result.markdown[audience], notes.model_dump(mode="json"), verified
            )
        self.store.update_run(
            run_id,
            status="done",
            group_count=result.group_count,
            commit_count=result.commit_count,
            prompt_versions=result.prompt_versions,
            routing={**self.engine.routing.summary(), "served_by": result.models},
            usage=result.usage.model_dump(mode="json"),
            lease_until=None,
            finished_at=utcnow(),
        )
        self._event(
            run_id,
            "done",
            f"Done: {sum(len(n.all_items()) for n in result.outputs.values())} items, "
            f"{result.usage.total_tokens} tokens, ${result.usage.usd:.4f} at paid rates",
            {
                "status": "done",
                "commit_count": result.commit_count,
                "group_count": result.group_count,
                "usage": result.usage.model_dump(mode="json"),
            },
        )
        try:
            from .observability import export_run

            export_run(self.engine.settings, run_id, ledger, {"repo": collected.repo})
        except Exception:
            log.exception("trace export failed for run %s", run_id)
        return ProcessOutcome(run_id, "done")
