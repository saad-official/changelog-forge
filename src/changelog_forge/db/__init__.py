"""Persistence: the Store protocol, an in-memory implementation, and Postgres."""

from __future__ import annotations

from ..config import AppSettings
from .store import MemoryStore, RunRecord, Store, StoredOutput

__all__ = ["MemoryStore", "RunRecord", "Store", "StoredOutput", "make_store"]


def make_store(settings: AppSettings) -> Store:
    """Postgres when DATABASE_URL is set, otherwise a process-local MemoryStore.

    The memory fallback is right for tests, the CLI and the GitHub Action (one process, one
    run). It is wrong for a multi-instance deploy (Vercel): runs created on one instance are
    invisible to another, so production must set DATABASE_URL.
    """
    if settings.database_url is not None and settings.database_url.get_secret_value():
        from .postgres import PostgresStore

        return PostgresStore(settings.database_url.get_secret_value())
    return MemoryStore()
