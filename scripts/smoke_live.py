"""One real run, end to end: real GitHub, real models, real ledger. Manual use only.

    uv run python scripts/smoke_live.py                       # default range below
    uv run python scripts/smoke_live.py honojs/hono v4.13.10..v4.13.13

Needs GROQ_API_KEY (and GEMINI_API_KEY for the fallback) in .env; GITHUB_TOKEN optional.
Prints both documents' first lines, the verification report and the ledger, and writes
everything to runs/smoke-<timestamp>/ (gitignored) so docs/costs.md can quote real numbers.
This is the counterpart of the stubbed test suite: it proves the fakes resemble reality.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from llm_kit import Ledger

from changelog_forge.collect.refs import resolve_target
from changelog_forge.config import AppSettings
from changelog_forge.db import MemoryStore
from changelog_forge.engine import Engine
from changelog_forge.pipeline import Pipeline

DEFAULT = ("honojs/hono", "v4.13.10..v4.13.13")


def main() -> None:
    repo, range_ = (sys.argv[1], sys.argv[2]) if len(sys.argv) > 2 else DEFAULT
    settings = AppSettings()
    engine = Engine.from_settings(settings, store=MemoryStore())
    spec = resolve_target(repo, *range_.replace("...", "..").split("..", 1))

    started = time.monotonic()
    github = engine.github_builder(None)
    collected = github.collect(spec)
    github.close()
    collect_s = time.monotonic() - started
    print(
        f"collected {len(collected.commits)} commits in {collect_s:.1f}s "
        f"({collected.api_calls} GitHub calls)"
    )

    ledger = Ledger(max_usd=engine.budget_usd)
    map_llm, reduce_llm = engine.llm_builder(ledger)
    pipeline = Pipeline(
        map_llm=map_llm,
        reduce_llm=reduce_llm,
        ledger=ledger,
        emit=lambda kind, message, data: print(f"  [{kind}] {message}"),
        prompt_versions=dict(engine.routing.prompts),
        target_tokens=engine.routing.chunk.target_tokens,
        budget_usd=engine.budget_usd,
    )
    result = pipeline.run(collected, ["user", "dev"])
    total_s = time.monotonic() - started

    out = Path("runs") / f"smoke-{datetime.now(UTC):%Y%m%dT%H%M%S}"
    out.mkdir(parents=True, exist_ok=True)
    for audience, markdown in result.markdown.items():
        (out / f"{audience}.md").write_text(markdown, encoding="utf-8")
    ledger.write_jsonl(out / "ledger.jsonl")
    summary = {
        "repo": spec.repo,
        "range": f"{spec.base}...{spec.head}",
        "commits": result.commit_count,
        "groups": result.group_count,
        "seconds": round(total_s, 1),
        "models": result.models,
        "fallbacks": map_llm.fallback_reasons + reduce_llm.fallback_reasons,
        "usage": result.usage.model_dump(mode="json"),
        "usd_per_100_commits": round(result.usage.usd / max(1, result.commit_count) * 100, 6),
        "verification": result.verification.model_dump(mode="json"),
        "pacer_slept_s": round(engine.pacer.slept_s, 1),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("\n" + result.markdown["user"][:1200])
    print("\n" + result.markdown["dev"][:1200])
    print(
        f"\nverification: {len(result.verification.dropped_refs)} dropped refs, "
        f"{len(result.verification.downgraded)} downgraded, "
        f"{len(result.verification.uncovered_inputs)} fallback items, "
        f"degraded: {result.verification.degraded or 'none'}"
    )
    print(f"models: {result.models}  fallbacks: {summary['fallbacks'] or 'none'}")
    print(f"ledger: {ledger.summary()}")
    print(f"per 100 commits: ${summary['usd_per_100_commits']:.6f}  wall: {total_s:.1f}s")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
