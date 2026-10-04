"""`uv run migrate`: apply db/migrations/*.sql in order, once each. `uv run purge`: delete
runs older than 30 days (the daily job; also exposed as POST /api/cron/purge).

Plain SQL files and a ten-line runner instead of Alembic: the schema is small, the files
are readable on their own, and there is no ORM whose models need to stay in sync.
"""

from __future__ import annotations

import sys
from datetime import timedelta
from importlib import resources

import psycopg

from ..config import get_settings
from ..models import utcnow

RETENTION_DAYS = 30


def migration_files() -> list[tuple[str, str]]:
    folder = resources.files("changelog_forge.db") / "migrations"
    files = sorted(
        (entry.name, entry.read_text(encoding="utf-8"))
        for entry in folder.iterdir()
        if entry.name.endswith(".sql")
    )
    return files


def apply_migrations(dsn: str) -> list[str]:
    applied: list[str] = []
    with psycopg.connect(dsn, prepare_threshold=None, autocommit=False) as conn:
        conn.execute("CREATE SCHEMA IF NOT EXISTS changelog_forge")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS changelog_forge.schema_migrations (
                   name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"""
        )
        conn.commit()
        done = {
            row[0] for row in conn.execute("SELECT name FROM changelog_forge.schema_migrations")
        }
        for name, sql in migration_files():
            if name in done:
                continue
            # One transaction per file: a failing migration leaves no half-applied schema.
            with conn.transaction():
                conn.execute(sql)
                conn.execute(
                    "INSERT INTO changelog_forge.schema_migrations (name) VALUES (%s)", (name,)
                )
            applied.append(name)
    return applied


def _dsn() -> str:
    settings = get_settings()
    if settings.database_url is None or not settings.database_url.get_secret_value():
        print("DATABASE_URL is not set (see .env.example).", file=sys.stderr)
        raise SystemExit(2)
    return settings.database_url.get_secret_value()


def main() -> None:
    applied = apply_migrations(_dsn())
    print(f"applied: {', '.join(applied)}" if applied else "database is up to date")


def purge_main() -> None:
    from .postgres import PostgresStore

    store = PostgresStore(_dsn())
    try:
        removed = store.purge_runs(utcnow() - timedelta(days=RETENTION_DAYS))
    finally:
        store.close()
    print(f"purged {removed} run(s) older than {RETENTION_DAYS} days")


if __name__ == "__main__":
    main()
