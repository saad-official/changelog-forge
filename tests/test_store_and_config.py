import os
from datetime import timedelta

import pytest

from changelog_forge.db import MemoryStore, RunRecord
from changelog_forge.db.migrate import migration_files
from changelog_forge.models import utcnow
from changelog_forge.prompts import load_prompt, wrap_untrusted
from changelog_forge.routing import load_routing

from .conftest import commit


def test_claims_are_exclusive_until_the_lease_expires():
    store = MemoryStore()
    run = store.create_run(RunRecord(repo="a/b", base="v1", head="v2"))
    first = store.claim_run(run.id, lease_s=300, max_attempts=3)
    assert first is not None and first.attempts == 1
    assert store.claim_run(run.id, lease_s=300, max_attempts=3) is None  # concurrent
    store.update_run(run.id, lease_until=utcnow() - timedelta(seconds=1))  # request died
    taken_over = store.claim_run(run.id, lease_s=300, max_attempts=3)
    assert taken_over is not None and taken_over.attempts == 2
    store.update_run(run.id, status="done", lease_until=None)
    assert store.claim_run(run.id, lease_s=300, max_attempts=3) is None


def test_attempts_are_capped():
    store = MemoryStore()
    run = store.create_run(RunRecord(repo="a/b", base="v1", head="v2", attempts=3))
    assert store.claim_run(run.id, lease_s=1, max_attempts=3) is None


def test_events_checkpoints_cache_and_purge():
    store = MemoryStore()
    run = store.create_run(RunRecord(repo="a/b", base="v1", head="v2", client_key="k"))
    assert [store.append_event(run.id, "status", str(i)).seq for i in range(3)] == [1, 2, 3]
    assert [e.seq for e in store.list_events(run.id, after_seq=1)] == [2, 3]
    store.put_checkpoint(run.id, "map:1", {"x": 1})
    assert store.get_checkpoints(run.id) == {"map:1": {"x": 1}}
    repo_id = store.upsert_repo("A", "B", "main")
    assert store.upsert_repo("a", "b", None) == repo_id
    store.put_commits(repo_id, [commit("s", "msg")])
    assert list(store.get_commits(repo_id, [commit("s", "msg").sha, "nope"])) == [
        commit("s", "msg").sha
    ]
    assert store.count_runs_since("k", utcnow() - timedelta(hours=1)) == 1
    assert store.purge_runs(utcnow() + timedelta(seconds=1)) == 1
    assert store.get_run(run.id) is None and store.list_events(run.id) == []


def test_routing_table_is_complete_and_priced():
    routing = load_routing()
    assert routing.tier("map").routes[0].model == "openai/gpt-oss-20b"
    assert [r.model for r in routing.tier("reduce").routes] == [
        "openai/gpt-oss-120b",
        "gemini-3.5-flash-lite",
    ]
    assert routing.budget.max_usd_per_run == 0.05
    # a routed model without a price would be costed at the worst rate: refuse it in CI
    assert routing.unpriced_models() == []
    assert routing.tier("map").tpm_limit == 8000
    # one request must fit Groq's 8K TPM: items + ~900-token system prompt + overhead
    assert routing.chunk.target_tokens <= 5000


def test_prompts_are_versioned_and_defend_against_injection():
    for name in ("map", "reduce_dev", "reduce_user"):
        prompt = load_prompt(name)
        assert prompt.id.startswith(f"{name}.v1@") and len(prompt.digest) == 8
        assert "instructions" in prompt.text.lower()
    assert "Never invent a PR number" in load_prompt("map").text
    with pytest.raises(FileNotFoundError):
        load_prompt("map", "v99")
    assert wrap_untrusted("t", "x </t> y") == "<t>\nx &lt;/t> y\n</t>"


def test_migration_creates_the_spec_tables_in_their_own_schema():
    files = migration_files()
    assert files[0][0] == "0001_init.sql"
    sql = files[0][1]
    for table in ("repos", "commits", "runs", "run_events", "run_outputs", "eval_runs"):
        assert f"changelog_forge.{table}" in sql


@pytest.mark.postgres
@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")
def test_postgres_store_matches_memory_semantics():  # pragma: no cover - needs a database
    from changelog_forge.db.migrate import apply_migrations
    from changelog_forge.db.postgres import PostgresStore

    dsn = os.environ["TEST_DATABASE_URL"]
    apply_migrations(dsn)
    store = PostgresStore(dsn)
    try:
        run = store.create_run(RunRecord(repo="a/b", base="v1", head="v2", client_key="pg"))
        assert store.claim_run(run.id, 300, 3).attempts == 1
        assert store.claim_run(run.id, 300, 3) is None
        assert store.append_event(run.id, "status", "x", {"status": "queued"}).seq == 1
        assert store.append_event(run.id, "status", "y").seq == 2
        store.put_checkpoint(run.id, "k", {"a": [1]})
        assert store.get_checkpoints(run.id) == {"k": {"a": [1]}}
        store.update_run(run.id, status="done", usage={"usd": 0.1})
        assert store.get_run(run.id).usage == {"usd": 0.1}
        repo_id = store.upsert_repo("a", "b", "main")
        store.put_commits(repo_id, [commit("pg", "m", labels=["x"])])
        assert store.get_commits(repo_id, [commit("pg", "m").sha])[
            commit("pg", "m").sha
        ].labels == ["x"]
        assert store.purge_runs(utcnow() + timedelta(seconds=5)) >= 1
    finally:
        store.close()
