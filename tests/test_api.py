import json
import time
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import SecretStr

from changelog_forge.api.main import create_app
from changelog_forge.collect.github import RateLimited, RepoNotFound, TooManyCommits
from changelog_forge.db import MemoryStore
from changelog_forge.dispatch import body_hash, sign_for_tests
from changelog_forge.models import utcnow

from .conftest import make_engine

pytestmark = pytest.mark.anyio


def client_for(engine) -> httpx.AsyncClient:
    app = create_app(engine)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def sse_events(text: str) -> list[dict]:
    events = []
    for block in text.split("\n\n"):
        data = [line[6:] for line in block.splitlines() if line.startswith("data: ")]
        if data:
            events.append(json.loads("\n".join(data)))
    return events


async def test_health(settings):
    async with client_for(make_engine(settings)) as client:
        response = await client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] and body["db"] and body["store"] == "memory"
    assert body["providers"] == {"groq": True, "gemini": False}
    assert body["dispatch"] == "background"


async def test_full_run_lifecycle(settings, sample_range):
    engine = make_engine(settings, collected_range=sample_range)
    async with client_for(engine) as client:
        created = await client.post(
            "/api/runs",
            json={"repo": "acme/widgets", "base": "v1.0.0", "head": "v1.1.0", "github_token": "t"},
        )
        assert created.status_code == 202
        body = created.json()
        assert body["status"] == "queued" and body["process"] == "background"
        assert body["commit_count"] == 6
        run_id = body["id"]

        # The background task ran after the 202 (ASGITransport waits for it).
        run = (await client.get(f"/api/runs/{run_id}")).json()
        assert run["status"] == "done"
        assert run["audiences"] == ["user", "dev"]
        assert run["created_at"] and run["finished_at"]
        assert run["group_count"] == 1
        dev = run["outputs"]["dev"]["json"]
        assert dev["sections"][0]["category"] == "breaking"
        ref = dev["sections"][0]["items"][0]["refs"][0]
        assert ref["kind"] == "pr" and ref["id"] == "#11" and ref["url"].startswith("https://")
        assert run["outputs"]["user"]["markdown"].startswith("## What's new in acme/widgets")
        assert run["verified"]["checked_refs"] == 5 and run["verified"]["downgraded"] == []
        usage = run["usage"]
        assert usage["calls"] == 3 and usage["max_usd"] == 0.05
        assert {row["stage"] for row in usage["by_model"]} == {"map", "reduce"}
        assert run["prompt_versions"]["map"].startswith("map.v1@")

        stream = await client.get(f"/api/runs/{run_id}/events")
        assert stream.headers["content-type"].startswith("text/event-stream")
        assert "event:" not in stream.text  # unnamed events only
        events = sse_events(stream.text)
        assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
        assert events[-1]["kind"] == "done"
        assert events[-1]["data"]["status"] == "done"
        assert events[-1]["data"]["commit_count"] == 6
        assert all("level" in e["data"] and e["at"] for e in events)
        statuses = [e["data"]["status"] for e in events if e["kind"] == "status"]
        assert statuses == ["collecting", "queued", "mapping", "reducing", "verifying"]
        assert any(e["data"].get("groups") == 1 for e in events)

        replay = await client.get(
            f"/api/runs/{run_id}/events", headers={"Last-Event-ID": str(len(events) - 1)}
        )
        assert [e["kind"] for e in sse_events(replay.text)] == ["done"]

        md = await client.get(f"/api/runs/{run_id}.md", params={"audience": "dev"})
        assert md.status_code == 200
        assert md.headers["content-type"].startswith("text/markdown")
        assert md.headers["content-disposition"] == (
            'attachment; filename="acme-widgets-v1.1.0-dev.md"'
        )

        again = await client.post(f"/api/runs/{run_id}/process")
        assert again.status_code == 200 and again.json()["status"] == "done"

    # the per-run token was used for collection and never stored anywhere
    stored = json.dumps(engine.store.get_run(run_id).model_dump(mode="json"))
    assert '"t"' not in stored and "github_token" not in stored


async def test_client_dispatch_on_vercel_and_process_conflicts(settings):
    settings.vercel = True
    engine = make_engine(settings)
    async with client_for(engine) as client:
        created = (
            await client.post("/api/runs", json={"repo": "a/b", "base": "v1", "head": "v2"})
        ).json()
        assert created["process"] == "client"
        assert created["process_url"] == f"/api/runs/{created['id']}/process"
        assert engine.store.get_run(created["id"]).status == "queued"  # nothing ran

        # another request holds a fresh lease -> 409
        engine.store.claim_run(created["id"], lease_s=300, max_attempts=3)
        conflict = await client.post(created["process_url"])
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "run_in_progress"

        # that request died: its lease expired, so the next call takes over and finishes
        engine.store.update_run(created["id"], lease_until=utcnow() - timedelta(seconds=1))
        done = await client.post(created["process_url"])
        assert done.status_code == 200 and done.json()["status"] == "done"


async def test_qstash_signed_process_calls_are_verified(settings):
    settings.qstash_current_signing_key = SecretStr("sig-key")
    settings.public_api_url = "https://api.example.com"
    settings.vercel = True
    engine = make_engine(settings)
    async with client_for(engine) as client:
        run_id = (
            await client.post("/api/runs", json={"repo": "a/b", "base": "v1", "head": "v2"})
        ).json()["id"]
        url = f"https://api.example.com/api/runs/{run_id}/process"
        now = time.time()
        claims = {
            "iss": "Upstash",
            "sub": url,
            "exp": now + 60,
            "nbf": now,
            "body": body_hash(b"{}"),
        }
        bad = await client.post(
            f"/api/runs/{run_id}/process",
            content=b"{}",
            headers={"Upstash-Signature": sign_for_tests(claims, "wrong")},
        )
        assert bad.status_code == 401 and bad.json()["detail"]["code"] == "unauthorized"
        good = await client.post(
            f"/api/runs/{run_id}/process",
            content=b"{}",
            headers={"Upstash-Signature": sign_for_tests(claims, "sig-key")},
        )
        assert good.status_code == 200 and good.json()["status"] == "done"


async def test_rate_limit_is_ten_runs_per_hour_with_retry_after(settings):
    async with client_for(make_engine(settings)) as client:
        for _ in range(10):
            ok = await client.post("/api/runs", json={"repo": "a/b", "base": "v1", "head": "v2"})
            assert ok.status_code == 202
        limited = await client.post("/api/runs", json={"repo": "a/b", "base": "v1", "head": "v2"})
    assert limited.status_code == 429
    assert limited.json()["detail"]["code"] == "rate_limited"
    assert int(limited.headers["retry-after"]) > 0
    assert limited.json()["detail"]["retry_after"] == int(limited.headers["retry-after"])


async def test_postgres_count_limits_across_instances(settings):
    store = MemoryStore()
    from changelog_forge.api.ratelimit import client_key
    from changelog_forge.db import RunRecord

    key = client_key("127.0.0.1", settings)
    for _ in range(10):  # runs created by "other instances": this app's bucket is still full
        store.create_run(RunRecord(repo="a/b", base="v1", head="v2", client_key=key))
    async with client_for(make_engine(settings, store)) as client:
        transport_ip_run = await client.post(
            "/api/runs", json={"repo": "a/b", "base": "v1", "head": "v2"}
        )
    assert transport_ip_run.status_code == 429


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (RepoNotFound("nope"), 404, "repo_not_found"),
        (TooManyCommits("too many"), 422, "commit_cap"),
        (
            RateLimited("slow down", reset_at=datetime.now(UTC) + timedelta(minutes=5)),
            429,
            "rate_limited",
        ),
    ],
)
async def test_collection_errors_are_returned_with_codes(settings, error, status, code):
    engine = make_engine(settings, github_error=error)
    async with client_for(engine) as client:
        response = await client.post("/api/runs", json={"repo": "a/b", "base": "v1", "head": "v2"})
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    if status == 429:
        assert 200 < int(response.headers["retry-after"]) <= 300


async def test_bad_input_and_missing_runs(settings):
    async with client_for(make_engine(settings)) as client:
        bad = await client.post(
            "/api/runs", json={"repo": "not a repo", "base": "v1", "head": "v2"}
        )
        assert bad.status_code == 400
        assert bad.json()["detail"] == {
            "code": "bad_request",
            "message": "expected a repository like 'owner/name', got 'not a repo'",
            "field": "repo",
        }
        no_range = await client.post("/api/runs", json={"repo": "a/b"})
        assert no_range.json()["detail"]["field"] == "range"
        assert (
            await client.post("/api/runs", json={"repo": "a/b", "audiences": []})
        ).status_code == 422
        for path in ("/api/runs/nope", "/api/runs/nope.md", "/api/runs/nope/events"):
            missing = await client.get(path)
            assert missing.status_code == 404
            assert missing.json()["detail"]["code"] == "run_not_found"


async def test_cors_preflight_and_exposed_headers(settings):
    async with client_for(make_engine(settings)) as client:
        preflight = await client.options(
            "/api/runs",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == "http://localhost:3000"
        simple = await client.get("/api/health", headers={"Origin": "http://localhost:3000"})
        assert "Retry-After" in simple.headers["access-control-expose-headers"]
        evil = await client.get("/api/health", headers={"Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in evil.headers


async def test_cron_endpoints_need_the_secret(settings):
    async with client_for(make_engine(settings)) as client:
        assert (await client.post("/api/cron/purge")).status_code == 401
        wrong = await client.get("/api/cron/purge", headers={"Authorization": "Bearer nope"})
        assert wrong.status_code == 401
        ok = await client.get("/api/cron/purge", headers={"Authorization": "Bearer cron-test"})
        assert ok.status_code == 200 and ok.json() == {"purged": 0}
        assert (await client.post("/api/evals/run")).status_code == 401


async def test_openapi_is_served_under_api(settings):
    async with client_for(make_engine(settings)) as client:
        spec = (await client.get("/api/openapi.json")).json()
        assert "/api/runs" in spec["paths"] and "/api/runs/{run_id}/events" in spec["paths"]
        assert (await client.get("/api/docs")).status_code == 200


async def test_a_run_that_runs_out_of_time_is_resumable(settings, sample_range):
    settings.vercel = True
    settings.process_time_budget_s = -1.0  # already past: suspends before the first map call
    engine = make_engine(settings, collected_range=sample_range)
    async with client_for(engine) as client:
        created = await client.post("/api/runs", json={"repo": "a/b", "base": "v1", "head": "v2"})
        run_id = created.json()["id"]
        paused = await client.post(f"/api/runs/{run_id}/process")
        assert paused.status_code == 202 and paused.json()["resumable"] is True
        run = engine.store.get_run(run_id)
        assert run.status == "mapping" and run.lease_until is None and run.attempts == 0

        settings.process_time_budget_s = 240
        done = await client.post(f"/api/runs/{run_id}/process")
        assert done.status_code == 200 and done.json()["status"] == "done"
        events = sse_events((await client.get(f"/api/runs/{run_id}/events")).text)
        assert any(e["data"].get("stage") == "suspended" for e in events)
        assert (await client.get(f"/api/runs/{run_id}")).json()["usage"]["calls"] == 3
