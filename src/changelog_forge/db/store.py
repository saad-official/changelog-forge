"""The persistence boundary: one `Store` protocol, two implementations.

    PostgresStore   production (Neon), db/postgres.py
    MemoryStore     tests, the CLI without DATABASE_URL, the GitHub Action

The protocol is deliberately narrow and synchronous. llm-kit is synchronous, so the
pipeline runs in a worker thread; a sync store is callable from that thread directly, and
FastAPI runs sync endpoints in its threadpool. An async driver would force every pipeline
step to hop back onto the event loop for a database write, for no throughput gain at this
scale (decision recorded in docs/architecture.md, "Why psycopg 3").
"""

from __future__ import annotations

import threading
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Protocol
from uuid import uuid4

from pydantic import BaseModel, Field

from ..models import TERMINAL_STATUSES, CommitRecord, RunEvent, RunStatus, utcnow


class RunRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    repo: str
    base: str
    head: str
    status: RunStatus = "queued"
    audiences: list[str] = Field(default_factory=lambda: ["user", "dev"])
    commit_count: int | None = None
    group_count: int | None = None
    prompt_versions: dict[str, Any] = Field(default_factory=dict)
    routing: dict[str, Any] = Field(default_factory=dict)
    usage: dict[str, Any] | None = None
    error: str | None = None
    client_key: str | None = None
    attempts: int = 0
    lease_until: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None


class StoredOutput(BaseModel):
    audience: str
    markdown: str
    json_doc: dict[str, Any]
    verified: dict[str, Any]


class Store(Protocol):
    # -- cache (see collect.github.CommitCache) ---------------------------------------
    def upsert_repo(self, owner: str, name: str, default_branch: str | None) -> int: ...
    def get_commits(self, repo_id: int, shas: list[str]) -> dict[str, CommitRecord]: ...
    def put_commits(self, repo_id: int, commits: list[CommitRecord]) -> None: ...
    def get_http_cache(self, key: str) -> tuple[str, Any] | None: ...
    def put_http_cache(self, key: str, etag: str, body: Any) -> None: ...

    # -- runs ---------------------------------------------------------------------------
    def ping(self) -> bool: ...
    def create_run(self, run: RunRecord) -> RunRecord: ...
    def get_run(self, run_id: str) -> RunRecord | None: ...
    def update_run(self, run_id: str, **fields: Any) -> None: ...
    def claim_run(self, run_id: str, lease_s: float, max_attempts: int) -> RunRecord | None: ...
    def release_run(self, run_id: str) -> None: ...
    def count_runs_since(self, client_key: str, since: datetime) -> int: ...

    # -- progress, checkpoints, outputs ------------------------------------------------
    def append_event(
        self, run_id: str, kind: str, message: str, data: dict[str, Any] | None = None
    ) -> RunEvent: ...
    def list_events(self, run_id: str, after_seq: int = 0) -> list[RunEvent]: ...
    def put_checkpoint(self, run_id: str, key: str, data: Any) -> None: ...
    def get_checkpoints(self, run_id: str) -> dict[str, Any]: ...
    def put_output(
        self,
        run_id: str,
        audience: str,
        markdown: str,
        json_doc: dict[str, Any],
        verified: dict[str, Any],
    ) -> None: ...
    def get_outputs(self, run_id: str) -> dict[str, StoredOutput]: ...

    # -- evals and maintenance ----------------------------------------------------------
    def put_eval_run(self, golden_set_version: str, scores: dict[str, Any]) -> str: ...
    def purge_runs(self, older_than: datetime) -> int: ...


def is_claimable(run: RunRecord, now: datetime, max_attempts: int) -> bool:
    """A run can be (re)processed when it is unfinished, unleased, and not out of attempts.

    The lease is what makes `/process` safe to call twice (QStash retry, a browser and a
    queue racing): the second caller sees an unexpired lease and backs off. It is also what
    makes a killed request recoverable: the lease simply expires and the next call resumes
    from the last checkpoint.
    """
    if run.status in TERMINAL_STATUSES or run.attempts >= max_attempts:
        return False
    return run.lease_until is None or run.lease_until <= now


class MemoryStore:
    """A thread-safe in-process Store. Same semantics as Postgres, no durability."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._repos: dict[tuple[str, str], int] = {}
        self._commits: dict[tuple[int, str], CommitRecord] = {}
        self._http: dict[str, tuple[str, Any]] = {}
        self._runs: dict[str, RunRecord] = {}
        self._events: dict[str, list[RunEvent]] = defaultdict(list)
        self._checkpoints: dict[str, dict[str, Any]] = defaultdict(dict)
        self._outputs: dict[str, dict[str, StoredOutput]] = defaultdict(dict)
        self.eval_runs: list[dict[str, Any]] = []

    # -- cache --------------------------------------------------------------------------
    def upsert_repo(self, owner: str, name: str, default_branch: str | None) -> int:
        with self._lock:
            key = (owner.lower(), name.lower())
            if key not in self._repos:
                self._repos[key] = len(self._repos) + 1
            return self._repos[key]

    def get_commits(self, repo_id: int, shas: list[str]) -> dict[str, CommitRecord]:
        with self._lock:
            return {
                sha: self._commits[(repo_id, sha)].model_copy(deep=True)
                for sha in shas
                if (repo_id, sha) in self._commits
            }

    def put_commits(self, repo_id: int, commits: list[CommitRecord]) -> None:
        with self._lock:
            for commit in commits:
                self._commits[(repo_id, commit.sha)] = commit.model_copy(deep=True)

    def get_http_cache(self, key: str) -> tuple[str, Any] | None:
        with self._lock:
            return self._http.get(key)

    def put_http_cache(self, key: str, etag: str, body: Any) -> None:
        with self._lock:
            self._http[key] = (etag, body)

    # -- runs ---------------------------------------------------------------------------
    def ping(self) -> bool:
        return True

    def create_run(self, run: RunRecord) -> RunRecord:
        with self._lock:
            self._runs[run.id] = run.model_copy(deep=True)
            return run

    def get_run(self, run_id: str) -> RunRecord | None:
        with self._lock:
            run = self._runs.get(run_id)
            return run.model_copy(deep=True) if run else None

    def update_run(self, run_id: str, **fields: Any) -> None:
        with self._lock:
            run = self._runs[run_id]
            self._runs[run_id] = run.model_copy(update=fields)

    def claim_run(self, run_id: str, lease_s: float, max_attempts: int) -> RunRecord | None:
        with self._lock:
            run = self._runs.get(run_id)
            now = utcnow()
            if run is None or not is_claimable(run, now, max_attempts):
                return None
            claimed = run.model_copy(
                update={
                    "attempts": run.attempts + 1,
                    "lease_until": now + timedelta(seconds=lease_s),
                }
            )
            self._runs[run_id] = claimed
            return claimed.model_copy(deep=True)

    def release_run(self, run_id: str) -> None:
        self.update_run(run_id, lease_until=None)

    def count_runs_since(self, client_key: str, since: datetime) -> int:
        with self._lock:
            return sum(
                1
                for run in self._runs.values()
                if run.client_key == client_key and run.created_at >= since
            )

    # -- events, checkpoints, outputs -------------------------------------------------
    def append_event(
        self, run_id: str, kind: str, message: str, data: dict[str, Any] | None = None
    ) -> RunEvent:
        with self._lock:
            events = self._events[run_id]
            event = RunEvent(
                run_id=run_id, seq=len(events) + 1, kind=kind, message=message, data=data or {}
            )
            events.append(event)
            return event

    def list_events(self, run_id: str, after_seq: int = 0) -> list[RunEvent]:
        with self._lock:
            return [event for event in self._events.get(run_id, []) if event.seq > after_seq]

    def put_checkpoint(self, run_id: str, key: str, data: Any) -> None:
        with self._lock:
            self._checkpoints[run_id][key] = data

    def get_checkpoints(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._checkpoints.get(run_id, {}))

    def put_output(
        self,
        run_id: str,
        audience: str,
        markdown: str,
        json_doc: dict[str, Any],
        verified: dict[str, Any],
    ) -> None:
        with self._lock:
            self._outputs[run_id][audience] = StoredOutput(
                audience=audience, markdown=markdown, json_doc=json_doc, verified=verified
            )

    def get_outputs(self, run_id: str) -> dict[str, StoredOutput]:
        with self._lock:
            return dict(self._outputs.get(run_id, {}))

    # -- evals and maintenance ----------------------------------------------------------
    def put_eval_run(self, golden_set_version: str, scores: dict[str, Any]) -> str:
        with self._lock:
            eval_id = str(uuid4())
            self.eval_runs.append(
                {"id": eval_id, "golden_set_version": golden_set_version, "scores": scores}
            )
            return eval_id

    def purge_runs(self, older_than: datetime) -> int:
        with self._lock:
            stale = [rid for rid, run in self._runs.items() if run.created_at < older_than]
            for rid in stale:
                self._runs.pop(rid, None)
                self._events.pop(rid, None)
                self._checkpoints.pop(rid, None)
                self._outputs.pop(rid, None)
            return len(stale)
