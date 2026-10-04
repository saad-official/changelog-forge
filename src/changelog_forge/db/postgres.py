"""PostgresStore: the Store protocol over psycopg 3 (sync) and a small connection pool.

Why psycopg 3 rather than asyncpg (the other serious option):

  - The pipeline runs in a worker thread because llm-kit is synchronous. psycopg 3 has a
    first-class sync API *and* an async one, so the same driver serves the threadpool now
    and an async rewrite later. asyncpg is async-only; every checkpoint write from the
    worker thread would need `asyncio.run_coroutine_threadsafe` back onto the event loop.
  - Neon's pooled endpoint is PgBouncer in transaction mode, which breaks server-side
    prepared statements. psycopg exposes `prepare_threshold=None` to turn them off; with
    asyncpg the equivalent is `statement_cache_size=0` - both work, but this is one more
    reason the choice is about ergonomics, not speed. At a few queries per second, driver
    throughput is irrelevant.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from psycopg import errors
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from ..models import CommitRecord, RunEvent
from .store import RunRecord, StoredOutput

S = "changelog_forge"

_RUN_COLUMNS = {
    "status",
    "commit_count",
    "group_count",
    "prompt_versions",
    "routing",
    "usage",
    "error",
    "attempts",
    "lease_until",
    "finished_at",
    "repo_id",
}
_JSON_COLUMNS = {"prompt_versions", "routing", "usage"}


class PostgresStore:
    def __init__(self, dsn: str, *, min_size: int = 1, max_size: int = 4):
        self.pool = ConnectionPool(
            dsn,
            min_size=min_size,
            max_size=max_size,
            open=False,
            kwargs={"prepare_threshold": None, "row_factory": dict_row},
        )
        self.pool.open(wait=False)

    def close(self) -> None:
        self.pool.close()

    def _execute(self, sql: str, params: Any = None) -> list[dict[str, Any]]:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall()) if cur.description else []

    # -- cache --------------------------------------------------------------------------
    def upsert_repo(self, owner: str, name: str, default_branch: str | None) -> int:
        rows = self._execute(
            f"""INSERT INTO {S}.repos (owner, name, default_branch) VALUES (%s, %s, %s)
                ON CONFLICT (owner, name) DO UPDATE
                SET default_branch = COALESCE(EXCLUDED.default_branch, {S}.repos.default_branch),
                    fetched_at = now()
                RETURNING id""",
            (owner.lower(), name.lower(), default_branch),
        )
        return int(rows[0]["id"])

    def get_commits(self, repo_id: int, shas: list[str]) -> dict[str, CommitRecord]:
        if not shas:
            return {}
        rows = self._execute(
            f"""SELECT sha, author, date, message, parents, html_url, pr_number, pr_title,
                       pr_body, pr_url, labels, files
                FROM {S}.commits WHERE repo_id = %s AND sha = ANY(%s)""",
            (repo_id, shas),
        )
        return {row["sha"]: CommitRecord(**row) for row in rows}

    def put_commits(self, repo_id: int, commits: list[CommitRecord]) -> None:
        if not commits:
            return
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.executemany(
                f"""INSERT INTO {S}.commits (repo_id, sha, author, date, message, parents,
                        html_url, pr_number, pr_title, pr_body, pr_url, labels, files)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (repo_id, sha) DO NOTHING""",
                [
                    (
                        repo_id,
                        c.sha,
                        c.author,
                        c.date,
                        c.message,
                        c.parents,
                        c.html_url,
                        c.pr_number,
                        c.pr_title,
                        c.pr_body,
                        c.pr_url,
                        Jsonb(c.labels),
                        Jsonb(c.files) if c.files is not None else None,
                    )
                    for c in commits
                ],
            )

    def get_http_cache(self, key: str) -> tuple[str, Any] | None:
        rows = self._execute(f"SELECT etag, body FROM {S}.http_cache WHERE key = %s", (key,))
        return (rows[0]["etag"], rows[0]["body"]) if rows else None

    def put_http_cache(self, key: str, etag: str, body: Any) -> None:
        self._execute(
            f"""INSERT INTO {S}.http_cache (key, etag, body) VALUES (%s, %s, %s)
                ON CONFLICT (key) DO UPDATE SET etag = EXCLUDED.etag, body = EXCLUDED.body,
                fetched_at = now()""",
            (key, etag, Jsonb(body)),
        )

    # -- runs ---------------------------------------------------------------------------
    def ping(self) -> bool:
        try:
            self._execute("SELECT 1")
            return True
        except Exception:
            return False

    def create_run(self, run: RunRecord) -> RunRecord:
        self._execute(
            f"""INSERT INTO {S}.runs (id, repo, base, head, status, audiences, commit_count,
                    group_count, prompt_versions, routing, usage, error, client_key, attempts,
                    lease_until, created_at, finished_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                run.id,
                run.repo,
                run.base,
                run.head,
                run.status,
                run.audiences,
                run.commit_count,
                run.group_count,
                Jsonb(run.prompt_versions),
                Jsonb(run.routing),
                Jsonb(run.usage) if run.usage is not None else None,
                run.error,
                run.client_key,
                run.attempts,
                run.lease_until,
                run.created_at,
                run.finished_at,
            ),
        )
        return run

    @staticmethod
    def _run(row: dict[str, Any]) -> RunRecord:
        row = dict(row)
        row["id"] = str(row["id"])
        row.pop("repo_id", None)
        return RunRecord(**row)

    def get_run(self, run_id: str) -> RunRecord | None:
        rows = self._execute(f"SELECT * FROM {S}.runs WHERE id = %s", (run_id,))
        return self._run(rows[0]) if rows else None

    def update_run(self, run_id: str, **fields: Any) -> None:
        unknown = set(fields) - _RUN_COLUMNS
        if unknown:
            raise ValueError(f"not updatable run columns: {sorted(unknown)}")
        if not fields:
            return
        assignments = ", ".join(f"{column} = %s" for column in fields)
        values = [
            Jsonb(value) if column in _JSON_COLUMNS and value is not None else value
            for column, value in fields.items()
        ]
        self._execute(f"UPDATE {S}.runs SET {assignments} WHERE id = %s", (*values, run_id))

    def claim_run(self, run_id: str, lease_s: float, max_attempts: int) -> RunRecord | None:
        # One statement, so two concurrent /process calls cannot both win: Postgres row
        # locking serialises the UPDATEs and the loser's WHERE no longer matches.
        rows = self._execute(
            f"""UPDATE {S}.runs
                SET attempts = attempts + 1, lease_until = now() + make_interval(secs => %s)
                WHERE id = %s AND status NOT IN ('done', 'failed') AND attempts < %s
                  AND (lease_until IS NULL OR lease_until <= now())
                RETURNING *""",
            (lease_s, run_id, max_attempts),
        )
        return self._run(rows[0]) if rows else None

    def release_run(self, run_id: str) -> None:
        self._execute(f"UPDATE {S}.runs SET lease_until = NULL WHERE id = %s", (run_id,))

    def count_runs_since(self, client_key: str, since: datetime) -> int:
        rows = self._execute(
            f"SELECT count(*) AS n FROM {S}.runs WHERE client_key = %s AND created_at >= %s",
            (client_key, since),
        )
        return int(rows[0]["n"])

    # -- events, checkpoints, outputs -------------------------------------------------
    def append_event(
        self, run_id: str, kind: str, message: str, data: dict[str, Any] | None = None
    ) -> RunEvent:
        sql = f"""INSERT INTO {S}.run_events (run_id, seq, kind, message, data)
                  SELECT %s, COALESCE(MAX(seq), 0) + 1, %s, %s, %s
                  FROM {S}.run_events WHERE run_id = %s
                  RETURNING run_id, seq, at, kind, message, data"""
        params = (run_id, kind, message, Jsonb(data or {}), run_id)
        try:
            row = self._execute(sql, params)[0]
        except errors.UniqueViolation:
            row = self._execute(sql, params)[0]  # lost a seq race once; the retry wins
        return RunEvent(**{**row, "run_id": str(row["run_id"])})

    def list_events(self, run_id: str, after_seq: int = 0) -> list[RunEvent]:
        rows = self._execute(
            f"""SELECT run_id, seq, at, kind, message, data FROM {S}.run_events
                WHERE run_id = %s AND seq > %s ORDER BY seq""",
            (run_id, after_seq),
        )
        return [RunEvent(**{**row, "run_id": str(row["run_id"])}) for row in rows]

    def put_checkpoint(self, run_id: str, key: str, data: Any) -> None:
        self._execute(
            f"""INSERT INTO {S}.run_checkpoints (run_id, key, data) VALUES (%s, %s, %s)
                ON CONFLICT (run_id, key) DO UPDATE SET data = EXCLUDED.data""",
            (run_id, key, Jsonb(data)),
        )

    def get_checkpoints(self, run_id: str) -> dict[str, Any]:
        rows = self._execute(
            f"SELECT key, data FROM {S}.run_checkpoints WHERE run_id = %s", (run_id,)
        )
        return {row["key"]: row["data"] for row in rows}

    def put_output(
        self,
        run_id: str,
        audience: str,
        markdown: str,
        json_doc: dict[str, Any],
        verified: dict[str, Any],
    ) -> None:
        self._execute(
            f"""INSERT INTO {S}.run_outputs (run_id, audience, markdown, json, verified)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (run_id, audience) DO UPDATE SET markdown = EXCLUDED.markdown,
                json = EXCLUDED.json, verified = EXCLUDED.verified""",
            (run_id, audience, markdown, Jsonb(json_doc), Jsonb(verified)),
        )

    def get_outputs(self, run_id: str) -> dict[str, StoredOutput]:
        rows = self._execute(
            f"SELECT audience, markdown, json, verified FROM {S}.run_outputs WHERE run_id = %s",
            (run_id,),
        )
        return {
            row["audience"]: StoredOutput(
                audience=row["audience"],
                markdown=row["markdown"],
                json_doc=row["json"],
                verified=row["verified"],
            )
            for row in rows
        }

    # -- evals and maintenance ----------------------------------------------------------
    def put_eval_run(self, golden_set_version: str, scores: dict[str, Any]) -> str:
        eval_id = str(uuid4())
        self._execute(
            f"INSERT INTO {S}.eval_runs (id, golden_set_version, scores) VALUES (%s, %s, %s)",
            (eval_id, golden_set_version, Jsonb(scores)),
        )
        return eval_id

    def purge_runs(self, older_than: datetime) -> int:
        rows = self._execute(
            f"DELETE FROM {S}.runs WHERE created_at < %s RETURNING id", (older_than,)
        )
        return len(rows)
