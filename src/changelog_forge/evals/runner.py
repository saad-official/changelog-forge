"""`uv run evals`: score the pipeline on the golden set.

    uv run evals                      recorded model outputs, no network (what CI runs)
    uv run evals --live               call the models; prints cost, writes docs/evals.md
    uv run evals --live --record      ... and overwrite each case's cassette.json
    uv run evals --live --judge       ... plus the LLM-judge prose scores (reported apart)
    uv run evals collect owner/repo base..head    snapshot a new case's input.json

Exit status 1 when any case fails a gate (hallucinated refs, invalid links, invalid JSON,
blown length budget, a forbidden claim), so CI fails on exactly those regressions.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from llm_kit import Ledger

from ..config import AppSettings
from ..db import MemoryStore
from ..engine import Engine
from ..models import Usage
from ..normalise import hint_category, normalise
from ..pipeline import DictCheckpoints, Pipeline
from .cassette import RecordingLLM, ReplayLLM
from .golden import (
    Case,
    Expected,
    cassette_path,
    golden_dir,
    load_expected,
    load_input,
    load_manifest,
    slug_for,
    write_json,
)
from .judge import judge_notes
from .scorers import score_case

SNAPSHOT_FILES = 25
SNAPSHOT_BODY = 2000

METRIC_COLUMNS = [
    ("coverage_recall", "coverage"),
    ("hallucinated_refs", "halluc."),
    ("dropped_by_verifier", "dropped"),
    ("breaking_recall", "brk R"),
    ("breaking_precision", "brk P"),
    ("category_accuracy", "category"),
    ("link_validity", "links"),
    ("length_budget", "budget"),
    ("json_valid", "json"),
    ("forbidden_claims", "forbidden"),
    ("fallback_items", "fallback"),
]


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "yes" if value else "NO"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def run_case(
    engine: Engine,
    case: Case,
    *,
    live: bool,
    record: bool = False,
    judge: bool = False,
    root: Path | None = None,
) -> dict[str, Any]:
    root = root or golden_dir()
    collected = load_input(case.slug, root)
    expected = load_expected(case.slug, root)
    ledger = Ledger(max_usd=engine.budget_usd)
    checkpoints = DictCheckpoints()
    tape: list[dict[str, Any]] = []
    if live:
        map_llm, reduce_llm = engine.llm_builder(ledger)
        if record:
            map_llm = RecordingLLM(map_llm, ledger, tape)
            reduce_llm = RecordingLLM(reduce_llm, ledger, tape)
    else:
        path = cassette_path(case.slug, root)
        if not path.is_file():
            return {"slug": case.slug, "skipped": "no cassette.json (run --live --record)"}
        cassette = json.loads(path.read_text(encoding="utf-8"))
        checkpoints.put("groups", cassette["groups"])
        served = cassette.get("served_by", {})
        map_llm = ReplayLLM(cassette["calls"], ledger, served.get("map", []))
        reduce_llm = ReplayLLM(cassette["calls"], ledger, served.get("reduce", []))

    pipeline = Pipeline(
        map_llm=map_llm,
        reduce_llm=reduce_llm,
        ledger=ledger,
        checkpoints=checkpoints,
        counter=engine.counter,
        prompt_versions=dict(engine.routing.prompts),
        target_tokens=engine.routing.chunk.target_tokens,
        budget_usd=engine.budget_usd,
    )
    result = pipeline.run(collected, ["user", "dev"])
    metrics = score_case(
        collected=collected,
        outputs=result.outputs,
        markdown=result.markdown,
        verification=result.verification,
        expected=expected,
    )
    report: dict[str, Any] = {
        "slug": case.slug,
        "repo": case.repo,
        "range": f"{case.base}...{case.head}",
        "commits": result.commit_count,
        "groups": result.group_count,
        "metrics": metrics,
        "usage": result.usage.model_dump(mode="json"),
        "models": result.models,
        "prompt_versions": result.prompt_versions,
    }
    if live and record:
        write_json(
            cassette_path(case.slug, root),
            {
                "recorded_at": datetime.now(UTC).isoformat(),
                "prompt_versions": result.prompt_versions,
                "routing": engine.routing.summary(),
                "groups": checkpoints.get("groups"),
                "served_by": {
                    "map": list(dict.fromkeys(getattr(map_llm, "served_by", []))),
                    "reduce": list(dict.fromkeys(getattr(reduce_llm, "served_by", []))),
                },
                "calls": tape,
            },
        )
        # Keep a readable copy of what was scored next to the cassette.
        (root / case.slug / "output.dev.md").write_text(result.markdown["dev"], encoding="utf-8")
        (root / case.slug / "output.user.md").write_text(result.markdown["user"], encoding="utf-8")
    if live and judge:
        items, _ = normalise(collected)
        judge_ledger = Ledger(max_usd=engine.budget_usd)
        _, judge_llm = engine.llm_builder(judge_ledger)
        report["judge"] = {
            audience: judge_notes(
                judge_llm, result.markdown[audience], [i.title for i in items], audience
            ).model_dump()
            for audience in ("user", "dev")
        }
        report["judge_usage"] = Usage.from_ledger(judge_ledger).model_dump(mode="json")
    return report


def run_golden_set(
    engine: Engine,
    *,
    live: bool,
    limit: int | None = None,
    record: bool = False,
    judge: bool = False,
    only: list[str] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    root = root or golden_dir()
    manifest = load_manifest(root)
    cases = [c for c in manifest.cases if c.status == "recorded" and (not only or c.slug in only)]
    if limit:
        cases = cases[:limit]
    reports = [
        run_case(engine, case, live=live, record=record, judge=judge, root=root) for case in cases
    ]
    scored = [r for r in reports if "metrics" in r]
    aggregate: dict[str, Any] = {}
    for key, _ in METRIC_COLUMNS:
        values = [r["metrics"][key] for r in scored if r["metrics"][key] is not None]
        aggregate[key] = round(statistics.fmean(values), 4) if values else None
    commits = sum(r["commits"] for r in scored)
    usd = sum(r["usage"]["usd"] for r in scored)
    tokens = sum(r["usage"]["total_tokens"] for r in scored)
    aggregate.update(
        {
            "cases": len(scored),
            "passed": sum(1 for r in scored if r["metrics"]["passed"]),
            "commits": commits,
            "total_tokens": tokens,
            "usd": round(usd, 6),
            "usd_per_100_commits": round(usd / commits * 100, 6) if commits else None,
        }
    )
    return {
        "golden_set_version": manifest.version,
        "mode": "live" if live else "recorded",
        "generated_at": datetime.now(UTC).isoformat(),
        "routing": engine.routing.summary(),
        "cases": reports,
        "todo": [c.model_dump() for c in manifest.cases if c.status != "recorded"],
        "aggregate": aggregate,
    }


def table(report: dict[str, Any]) -> str:
    header = ["case", "commits", *[label for _, label in METRIC_COLUMNS], "pass"]
    rows = [header, ["---"] * len(header)]
    for case in report["cases"]:
        if "metrics" not in case:
            rows.append([case["slug"], case.get("skipped", ""), *[""] * (len(header) - 2)])
            continue
        m = case["metrics"]
        rows.append(
            [
                case["slug"],
                str(case["commits"]),
                *[_fmt(m[key]) for key, _ in METRIC_COLUMNS],
                _fmt(m["passed"]),
            ]
        )
    agg = report["aggregate"]
    rows.append(
        [
            "**mean**",
            str(agg["commits"]),
            *[_fmt(agg[key]) for key, _ in METRIC_COLUMNS],
            f"{agg['passed']}/{agg['cases']}",
        ]
    )
    return "\n".join("| " + " | ".join(row) + " |" for row in rows)


def write_markdown(report: dict[str, Any], path: Path) -> None:
    agg = report["aggregate"]
    lines = [
        "# Evals",
        "",
        "Generated by `uv run evals"
        + (" --live" if report["mode"] == "live" else "")
        + f"` on {report['generated_at'][:19]}Z. Golden set "
        f"`{report['golden_set_version']}`, mode **{report['mode']}** "
        + (
            "(model responses replayed from each case's `cassette.json`; no network)."
            if report["mode"] == "recorded"
            else "(live model calls)."
        ),
        "",
        "Metric definitions: [`scorers.py`](../src/changelog_forge/evals/scorers.py). Gates "
        "(a case fails if violated): hallucinated refs = 0, links = 1.00, json = 1.00, "
        "budget = 1.00, forbidden claims = 0. `dropped` counts references the verifier "
        "removed before rendering (model hallucinations caught), `fallback` counts items "
        "rendered without a model summary.",
        "",
        table(report),
        "",
        f"Cost of this run at paid rates (judge calls excluded): **${agg['usd']:.6f}** for "
        f"{agg['commits']} commits ({agg['total_tokens']} tokens); "
        + (
            f"**${agg['usd_per_100_commits']:.6f} per 100 commits** (target < $0.01)."
            if agg["usd_per_100_commits"] is not None
            else "n/a per 100 commits."
        ),
        "",
        "Routing: "
        + ", ".join(f"{k}: {' -> '.join(v)}" for k, v in report["routing"]["tiers"].items()),
        "",
    ]
    judged = [c for c in report["cases"] if "judge" in c]
    if judged:
        lines += ["## Prose quality (LLM judge, 1-5, reported separately)", ""]
        lines += [
            "| case | audience | clarity | faithfulness | usefulness | note |",
            "|---|---|---|---|---|---|",
        ]
        for case in judged:
            for audience, score in case["judge"].items():
                lines.append(
                    f"| {case['slug']} | {audience} | {score['clarity']} | "
                    f"{score['faithfulness']} | {score['usefulness']} | {score['notes']} |"
                )
        lines.append("")
    if report["todo"]:
        lines += ["## Not yet recorded", ""]
        for case in report["todo"]:
            lines.append(f"- `{case['slug']}`: {case['todo']}")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def collect_case(repo_range: str, repo: str, token: str | None) -> Path:
    """Snapshot one range's input and a starter expected.json for hand curation."""
    from ..collect.refs import resolve_target

    settings = AppSettings()
    engine = Engine.from_settings(settings, store=MemoryStore())
    spec = resolve_target(repo, *repo_range.replace("...", "..").split("..", 1))
    github = engine.github_builder(token)
    try:
        collected = github.collect(spec)
    finally:
        github.close()
    # Keep snapshots small (target < 200 KB): the prompt shows at most 20 files and
    # 1,500 body characters per item anyway.
    for commit in collected.commits:
        commit.files = commit.files[:SNAPSHOT_FILES] if commit.files is not None else None
        commit.pr_body = commit.pr_body[:SNAPSHOT_BODY] if commit.pr_body else commit.pr_body
        commit.message = commit.message[:SNAPSHOT_BODY]
    root = golden_dir()
    slug = slug_for(spec.repo)
    write_json(root / slug / "input.json", collected.model_dump(mode="json"))
    expected_path = root / slug / "expected.json"
    if not expected_path.exists():
        items, _ = normalise(collected)
        template = Expected(
            repo=spec.repo,
            base=spec.base,
            head=spec.head,
            must_mention=[f"#{i.pr_number}" for i in items if i.pr_number is not None],
            categories={
                f"#{i.pr_number}": hint_category(i)
                for i in items
                if i.pr_number is not None and (i.labels or i.conventional_type)
            },
            notes="TEMPLATE: curate by reading input.json.",
        )
        write_json(expected_path, template.model_dump())
    size = (root / slug / "input.json").stat().st_size
    print(
        f"wrote {root / slug / 'input.json'} ({size // 1024} KB, {len(collected.commits)} commits)"
    )
    return root / slug


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "collect":
        parser = argparse.ArgumentParser(prog="evals collect")
        parser.add_argument("repo")
        parser.add_argument("range")
        args = parser.parse_args(argv[1:])
        settings = AppSettings()
        token = settings.github_token.get_secret_value() if settings.github_token else None
        collect_case(args.range, args.repo, token)
        return

    parser = argparse.ArgumentParser(prog="evals", description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--recorded", action="store_true", help="replay cassettes (default)")
    mode.add_argument("--live", action="store_true", help="call the models")
    parser.add_argument("--record", action="store_true", help="with --live: save cassettes")
    parser.add_argument("--judge", action="store_true", help="with --live: LLM-judge prose")
    parser.add_argument("--case", action="append", help="only this slug (repeatable)")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-write", action="store_true", help="do not write docs/evals.md")
    parser.add_argument("--out", default="docs/evals.md")
    args = parser.parse_args(argv)

    settings = AppSettings()
    engine = Engine.from_settings(settings, store=MemoryStore())
    if not args.live:
        from ..chunk import ApproxCounter

        engine.counter = ApproxCounter()  # groups come from the cassette; no tiktoken needed
    report = run_golden_set(
        engine,
        live=args.live,
        limit=args.limit,
        record=args.record and args.live,
        judge=args.judge and args.live,
        only=args.case,
    )
    print(table(report))
    agg = report["aggregate"]
    print(
        f"\n{agg['passed']}/{agg['cases']} cases passed; ${agg['usd']:.6f} at paid rates "
        f"for {agg['commits']} commits"
    )
    if not args.no_write:
        write_markdown(report, Path(args.out))
        print(f"wrote {args.out}")
    if any(not c["metrics"]["passed"] for c in report["cases"] if "metrics" in c):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
