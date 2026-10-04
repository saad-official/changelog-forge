"""`changelog-forge owner/repo v1.2.0..v1.3.0 --audience user,dev`

Same engine as the API, no server: collect -> pipeline -> Markdown (or JSON) on stdout or
in a file. Progress and the cost ledger go to stderr, so `> notes.md` captures only notes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer
from llm_kit import Ledger

from .collect.github import GitHubError
from .collect.refs import TargetError, resolve_target
from .config import AppSettings
from .engine import Engine
from .models import AUDIENCES, CollectedRange
from .pipeline import Pipeline

app = typer.Typer(add_completion=False, help=__doc__, no_args_is_help=True)


def engine_factory(settings: AppSettings) -> Engine:
    """Indirection for tests. The CLI caches commits in Postgres when DATABASE_URL is set,
    otherwise in memory for this one process."""
    from .db import make_store

    return Engine.from_settings(settings, store=make_store(settings))


def parse_audiences(value: str) -> list[str]:
    requested = [part.strip().lower() for part in value.split(",") if part.strip()]
    unknown = [part for part in requested if part not in AUDIENCES]
    if unknown or not requested:
        raise typer.BadParameter(f"audiences are 'user' and/or 'dev', got {value!r}")
    return [audience for audience in AUDIENCES if audience in requested]


def _err(message: str) -> None:
    typer.echo(message, err=True)


@app.command()
def main(
    repo: Annotated[str, typer.Argument(help="owner/name, or a GitHub compare URL")],
    range_: Annotated[
        str | None, typer.Argument(metavar="RANGE", help="base..head (tags, branches or SHAs)")
    ] = None,
    audience: Annotated[str, typer.Option("--audience", "-a", help="user,dev")] = "user,dev",
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON instead of Markdown")] = False,
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Write to this file")] = None,
    token: Annotated[
        str | None,
        typer.Option("--token", envvar="CHANGELOG_FORGE_TOKEN", help="GitHub token for this run"),
    ] = None,
    input_file: Annotated[
        Path | None,
        typer.Option("--input", help="Use a recorded CollectedRange JSON instead of GitHub"),
    ] = None,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="No progress on stderr")] = False,
) -> None:
    audiences = parse_audiences(audience)
    settings = AppSettings()
    engine = engine_factory(settings)
    log = (lambda message: None) if quiet else _err

    if input_file is not None:
        collected = CollectedRange.model_validate_json(input_file.read_text(encoding="utf-8"))
    else:
        try:
            base, head = range_.replace("...", "..").split("..", 1) if range_ else (None, None)
            spec = resolve_target(repo, base or None, head or None)
        except (TargetError, ValueError) as exc:
            _err(f"error: {exc}")
            raise typer.Exit(2) from exc
        github = engine.github_builder(token)
        log(f"collecting {spec.repo} {spec.base}...{spec.head}")
        try:
            collected = github.collect(
                spec, on_progress=lambda stage, current, total: log(f"  {stage} {current}/{total}")
            )
        except GitHubError as exc:
            _err(f"error: {exc.message}")
            raise typer.Exit(3) from exc
        finally:
            github.close()
        log(
            f"collected {len(collected.commits)} commits "
            f"({collected.api_calls} API calls, {collected.cache_hits} cached)"
        )

    ledger = Ledger(max_usd=engine.budget_usd)
    map_llm, reduce_llm = engine.llm_builder(ledger)
    pipeline = Pipeline(
        map_llm=map_llm,
        reduce_llm=reduce_llm,
        ledger=ledger,
        emit=lambda kind, message, data: log(f"[{kind}] {message}"),
        counter=engine.counter,
        prompt_versions=dict(engine.routing.prompts),
        target_tokens=engine.routing.chunk.target_tokens,
        budget_usd=engine.budget_usd,
    )
    result = pipeline.run(collected, audiences)

    if as_json:
        text = json.dumps(
            {
                "outputs": {a: n.model_dump(mode="json") for a, n in result.outputs.items()},
                "verification": result.verification.model_dump(mode="json"),
                "usage": result.usage.model_dump(mode="json"),
            },
            indent=2,
        )
    else:
        text = "\n---\n\n".join(result.markdown[a] for a in audiences)

    if out is not None:
        out.write_text(text, encoding="utf-8")
        log(f"wrote {out}")
    else:
        sys.stdout.write(text if text.endswith("\n") else text + "\n")
    log(f"ledger: {ledger.summary()}")
    if result.verification.degraded:
        log(f"degraded: {'; '.join(result.verification.degraded)}")


__all__ = ["app", "parse_audiences"]
