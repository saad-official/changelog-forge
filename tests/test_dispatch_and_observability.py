import json
import time

import httpx
import respx
from llm_kit import CallRecord, Ledger
from llm_kit import Usage as LLMUsage

from changelog_forge.config import AppSettings
from changelog_forge.dispatch import (
    body_hash,
    dispatch_mode,
    process_url,
    publish_to_qstash,
    sign_for_tests,
    verify_qstash_signature,
)
from changelog_forge.observability import export_run, langfuse_batch

URL = "https://api.example.com/api/runs/r1/process"


def claims(**overrides):
    now = time.time()
    data = {"iss": "Upstash", "sub": URL, "exp": now + 60, "nbf": now - 1, "body": body_hash(b"{}")}
    data.update(overrides)
    return data


def test_dispatch_mode_depends_on_platform_and_qstash():
    base = {"_env_file": None}
    assert dispatch_mode(AppSettings(**base)) == "background"
    assert dispatch_mode(AppSettings(**base, vercel=True)) == "client"
    assert (
        dispatch_mode(
            AppSettings(**base, vercel=True, qstash_token="t", public_api_url="https://x.dev")
        )
        == "qstash"
    )


def test_qstash_signature_verification():
    good = sign_for_tests(claims(), "current")
    assert verify_qstash_signature(good, b"{}", URL, ["current", "next"])
    assert verify_qstash_signature(
        sign_for_tests(claims(), "next"), b"{}", URL, ["current", "next"]
    )
    assert not verify_qstash_signature(good, b"{} ", URL, ["current"])  # body tampered
    assert not verify_qstash_signature(good, b"{}", URL + "x", ["current"])  # other URL
    assert not verify_qstash_signature(good, b"{}", URL, ["wrong"])
    expired = sign_for_tests(claims(exp=time.time() - 10), "current")
    assert not verify_qstash_signature(expired, b"{}", URL, ["current"])
    assert not verify_qstash_signature("not.a.jwt", b"{}", URL, ["current"])


@respx.mock
def test_publish_to_qstash_targets_the_process_url():
    settings = AppSettings(_env_file=None, qstash_token="tok", public_api_url="https://api.x.dev/")
    route = respx.post(url__startswith="https://qstash.upstash.io/v2/publish/").mock(
        return_value=httpx.Response(201, json={"messageId": "m"})
    )
    assert publish_to_qstash(settings, "r1")
    request = route.calls.last.request
    assert str(request.url).endswith("/v2/publish/https://api.x.dev/api/runs/r1/process")
    assert request.headers["authorization"] == "Bearer tok"
    assert process_url(settings, "r1") == "https://api.x.dev/api/runs/r1/process"


def ledger_with_calls() -> Ledger:
    ledger = Ledger()
    ledger.add(CallRecord("groq", "openai/gpt-oss-20b", "map:1", LLMUsage(100, 50, 10), 0.5))
    ledger.add(
        CallRecord("groq", "openai/gpt-oss-120b", "reduce:dev", LLMUsage(10, 5), 0.2, error="X")
    )
    return ledger


def test_langfuse_batch_has_a_trace_and_one_generation_per_call():
    batch = langfuse_batch("run-1", ledger_with_calls(), {"repo": "a/b"})
    assert [e["type"] for e in batch] == ["trace-create", "generation-create", "generation-create"]
    generation = batch[1]["body"]
    assert generation["traceId"] == "run-1" and generation["model"] == "openai/gpt-oss-20b"
    assert generation["usageDetails"] == {"input": 100, "output": 50}
    assert batch[2]["body"]["level"] == "ERROR"
    assert "prompt" not in json.dumps(batch).lower()  # metadata only, never prompt text


@respx.mock
def test_langfuse_export_is_off_without_keys_and_posts_with_them():
    assert export_run(AppSettings(_env_file=None), "r", ledger_with_calls(), {}) is False
    route = respx.post("https://cloud.langfuse.com/api/public/ingestion").mock(
        return_value=httpx.Response(207, json={})
    )
    settings = AppSettings(_env_file=None, langfuse_public_key="pk", langfuse_secret_key="sk")
    assert export_run(settings, "r", ledger_with_calls(), {}) is True
    assert route.calls.last.request.headers["authorization"].startswith("Basic ")
