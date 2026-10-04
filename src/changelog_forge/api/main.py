"""The HTTP API (spec section 6). OpenAPI at /api/docs.

    uvicorn changelog_forge.api.main:app --port 7860     (Docker / Render / local)
    main.py at the repository root re-exports `app`      (Vercel's Python runtime)

`create_app(engine)` builds an app around any Engine, which is how the tests run the real
routes against an in-memory store and a fake model. The default `app` builds its Engine
lazily on first use, so importing this module never opens a database connection.
"""

import asyncio
import json
from datetime import timedelta
from typing import Annotated, Any

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

from .. import __version__
from ..collect.github import GitHubError, RateLimited
from ..collect.refs import TargetError, resolve_target
from ..config import get_settings
from ..db import Store
from ..dispatch import dispatch_mode, process_url, publish_to_qstash, verify_qstash_signature
from ..engine import Engine
from ..models import TERMINAL_STATUSES, ReleaseNotes, Usage, Verification, utcnow
from ..observability import configure_logging
from ..service import RunService
from .ratelimit import TokenBucket, client_ip, client_key
from .schemas import (
    AudienceOutput,
    ErrorBody,
    Health,
    ProcessResult,
    RunCreate,
    RunCreated,
    RunView,
)

SSE_POLL_S = 0.5
SSE_MAX_S = 250.0  # under Vercel's 300 s limit; EventSource reconnects with Last-Event-ID
SSE_KEEPALIVE_S = 15.0


def _error(status: int, code: str, message: str, **extra: Any) -> HTTPException:
    """Every API error is `{"detail": {"code", "message", "retry_after"?, "field"?}}`."""
    body = ErrorBody(code=code, message=message, **extra)
    headers = {"Retry-After": str(body.retry_after)} if body.retry_after else None
    return HTTPException(
        status_code=status, detail=body.model_dump(mode="json", exclude_none=True), headers=headers
    )


def create_app(engine: Engine | None = None) -> FastAPI:
    settings = engine.settings if engine else get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="Changelog Forge API",
        version=__version__,
        description=(
            "A git range in, release notes for two audiences out. Create a run, follow its "
            "progress over Server-Sent Events, read both documents with their verification "
            "report and the run's token cost at paid rates."
        ),
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.engine = engine
    app.state.bucket = TokenBucket(settings.runs_per_hour_per_ip, 3600.0)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.web_origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "Last-Event-ID"],
        expose_headers=["Retry-After", "Content-Disposition"],
        max_age=600,
    )

    def get_engine() -> Engine:
        if app.state.engine is None:
            app.state.engine = Engine.from_settings(settings)
        return app.state.engine

    EngineDep = Annotated[Engine, Depends(get_engine)]

    def get_run_or_404(store: Store, run_id: str):
        try:
            run = store.get_run(run_id)
        except Exception as exc:  # invalid uuid text in Postgres, etc.
            raise _error(404, "run_not_found", "run not found") from exc
        if run is None:
            raise _error(404, "run_not_found", "run not found")
        return run

    def require_cron(authorization: str | None) -> None:
        secret = settings.cron_secret.get_secret_value() if settings.cron_secret else ""
        if not secret:
            raise _error(503, "cron_disabled", "CRON_SECRET is not configured")
        if authorization != f"Bearer {secret}":
            raise _error(401, "unauthorized", "missing or wrong bearer token")

    # ------------------------------------------------------------------ health

    @app.get("/api/health", response_model=Health, tags=["meta"])
    def health(engine: EngineDep) -> Health:
        from ..db.store import MemoryStore

        return Health(
            ok=True,
            version=__version__,
            providers={name: engine.settings.has_key(name) for name in ("groq", "gemini")},
            db=engine.store.ping(),
            store="memory" if isinstance(engine.store, MemoryStore) else "postgres",
            dispatch=dispatch_mode(engine.settings),
        )

    # ------------------------------------------------------------------ runs

    @app.post(
        "/api/runs",
        status_code=202,
        response_model=RunCreated,
        tags=["runs"],
        responses={
            400: {"model": ErrorBody},
            404: {"model": ErrorBody},
            422: {"model": ErrorBody},
            429: {"model": ErrorBody},
        },
    )
    def create_run(
        body: RunCreate, request: Request, background: BackgroundTasks, engine: EngineDep
    ) -> RunCreated:
        """Validate the range, collect it from GitHub synchronously (up to the commit cap),
        and queue the pipeline. Collection errors are returned here, not as a failed run."""
        key = client_key(client_ip(request, engine.settings), engine.settings)
        allowed, wait_s = app.state.bucket.take(key)
        recent = engine.store.count_runs_since(key, utcnow() - timedelta(hours=1))
        if not allowed or recent >= engine.settings.runs_per_hour_per_ip:
            limit = engine.settings.runs_per_hour_per_ip
            raise _error(
                429,
                "rate_limited",
                f"You can start {limit} runs per hour. Try again in a few minutes.",
                retry_after=max(1, int(wait_s) or 60),
            )
        try:
            spec = resolve_target(body.repo, body.base, body.head)
        except TargetError as exc:
            field = "repo" if "repositor" in str(exc) else "range"
            raise _error(400, "bad_request", str(exc), field=field) from exc
        service = RunService(engine)
        token = body.github_token.get_secret_value() if body.github_token else None
        try:
            run = service.create_run(spec, list(body.audiences), github_token=token, client_key=key)
        except RateLimited as exc:
            raise _error(
                429, exc.code, exc.message, retry_after=exc.retry_after, reset_at=exc.reset_at
            ) from exc
        except GitHubError as exc:
            raise _error(exc.status, exc.code, exc.message) from exc

        mode = dispatch_mode(engine.settings)
        if mode == "qstash" and not publish_to_qstash(engine.settings, run.id):
            mode = "background" if not engine.settings.vercel else "client"
        if mode == "background":
            background.add_task(service.process, run.id, engine.settings.process_time_budget_s)
        return RunCreated(
            id=run.id,
            status=run.status,
            commit_count=run.commit_count,
            process=mode,
            process_url=f"/api/runs/{run.id}/process",
            events_url=f"/api/runs/{run.id}/events",
        )

    @app.post(
        "/api/runs/{run_id}/process",
        response_model=ProcessResult,
        tags=["runs"],
        responses={
            202: {"model": ProcessResult},
            401: {"model": ErrorBody},
            409: {"model": ErrorBody},
        },
    )
    async def process_run(
        run_id: str,
        request: Request,
        engine: EngineDep,
        upstash_signature: Annotated[str | None, Header()] = None,
    ) -> JSONResponse:
        """Run or resume the pipeline for a queued run.

        200 when this call finished the run (or it was already finished); 202 with
        `resumable: true` when the request's time budget ran out (call again to continue
        from the last checkpoint); 409 `run_in_progress` while another call holds the
        run's lease. Leases expire (~270 s), so a request that died never strands a run."""
        if upstash_signature is not None:
            keys = [
                key.get_secret_value()
                for key in (
                    engine.settings.qstash_current_signing_key,
                    engine.settings.qstash_next_signing_key,
                )
                if key
            ]
            body = await request.body()
            if not keys or not verify_qstash_signature(
                upstash_signature, body, process_url(engine.settings, run_id), keys
            ):
                raise _error(401, "unauthorized", "QStash signature did not verify")
        await run_in_threadpool(get_run_or_404, engine.store, run_id)
        outcome = await run_in_threadpool(
            RunService(engine).process, run_id, engine.settings.process_time_budget_s
        )
        if outcome.status == "in_progress":
            raise _error(409, "run_in_progress", "another request is processing this run")
        result = ProcessResult(
            id=run_id, status=outcome.status, resumable=outcome.resumable, message=outcome.message
        )
        return JSONResponse(result.model_dump(), status_code=202 if outcome.resumable else 200)

    @app.get(
        "/api/runs/{run_id}.md",
        response_class=PlainTextResponse,
        tags=["runs"],
        responses={200: {"content": {"text/markdown": {}}}, 404: {"model": ErrorBody}},
    )
    def run_markdown(
        run_id: str,
        engine: EngineDep,
        audience: Annotated[str, Query(pattern="^(user|dev)$")] = "user",
    ) -> PlainTextResponse:
        run = get_run_or_404(engine.store, run_id)
        output = engine.store.get_outputs(run_id).get(audience)
        if output is None:
            raise _error(
                404, "not_ready", f"no {audience} notes for this run (status {run.status})"
            )
        name = f"{run.repo.replace('/', '-')}-{run.head}-{audience}.md".replace(" ", "_")
        return PlainTextResponse(
            output.markdown,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    @app.get(
        "/api/runs/{run_id}",
        response_model=RunView,
        response_model_by_alias=True,
        tags=["runs"],
        responses={404: {"model": ErrorBody}},
    )
    def get_run(run_id: str, engine: EngineDep) -> RunView:
        run = get_run_or_404(engine.store, run_id)
        outputs = engine.store.get_outputs(run_id)
        verified = next(iter(outputs.values())).verified if outputs else None
        return RunView(
            id=run.id,
            status=run.status,
            repo=run.repo,
            base=run.base,
            head=run.head,
            audiences=run.audiences,
            commit_count=run.commit_count,
            group_count=run.group_count,
            usage=Usage.model_validate(run.usage) if run.usage else None,
            outputs={
                audience: AudienceOutput(
                    markdown=output.markdown, json_doc=ReleaseNotes.model_validate(output.json_doc)
                )
                for audience, output in outputs.items()
            },
            verified=Verification.model_validate(verified) if verified else None,
            error=run.error,
            prompt_versions=run.prompt_versions,
            routing=run.routing,
            created_at=run.created_at,
            finished_at=run.finished_at,
        )

    @app.get(
        "/api/runs/{run_id}/events",
        tags=["runs"],
        responses={200: {"content": {"text/event-stream": {}}}, 404: {"model": ErrorBody}},
    )
    async def run_events(
        run_id: str,
        engine: EngineDep,
        last_event_id: Annotated[str | None, Header()] = None,
        after: Annotated[int, Query(ge=0)] = 0,
    ) -> StreamingResponse:
        """Server-Sent Events: replays the run's history, then tails until done or failed.

        Every event is an unnamed SSE message (`onmessage` receives it) whose `data` is a
        RunEvent JSON object; `id` is its sequence number, so a reconnecting EventSource
        resumes via Last-Event-ID. The stream closes after a `done` or `failed` event."""
        await run_in_threadpool(get_run_or_404, engine.store, run_id)
        start_seq = int(last_event_id) if last_event_id and last_event_id.isdigit() else after
        return StreamingResponse(
            _event_stream(engine.store, run_id, start_seq),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ------------------------------------------------------------------ cron

    @app.post("/api/evals/run", tags=["cron"])
    def run_evals(
        engine: EngineDep,
        authorization: Annotated[str | None, Header()] = None,
        mode: Annotated[str, Query(pattern="^(recorded|live)$")] = "recorded",
        limit: Annotated[int, Query(ge=1, le=10)] = 10,
    ) -> dict[str, Any]:
        """Run the golden set (bearer CRON_SECRET; GET too, because Vercel Cron sends GET)
        and store the scores in `eval_runs`. `live` calls the models; keep `limit` small on
        serverless so it fits the request time limit."""
        require_cron(authorization)
        from ..evals.runner import run_golden_set

        report = run_golden_set(engine, live=mode == "live", limit=limit)
        eval_id = engine.store.put_eval_run(report["golden_set_version"], report)
        return {"id": eval_id, **report}

    @app.post("/api/cron/purge", tags=["cron"])
    def purge(
        engine: EngineDep, authorization: Annotated[str | None, Header()] = None
    ) -> dict[str, int]:
        """Delete runs older than 30 days (the daily job)."""
        require_cron(authorization)
        removed = engine.store.purge_runs(utcnow() - timedelta(days=30))
        return {"purged": removed}

    # Vercel Cron sends GET (with `Authorization: Bearer $CRON_SECRET`): same handlers,
    # hidden from the schema so each operation is documented once.
    app.add_api_route("/api/evals/run", run_evals, methods=["GET"], include_in_schema=False)
    app.add_api_route("/api/cron/purge", purge, methods=["GET"], include_in_schema=False)

    return app


async def _event_stream(store: Store, run_id: str, after_seq: int):
    loop = asyncio.get_running_loop()
    started = last_ping = loop.time()
    seq = after_seq
    yield "retry: 2000\n\n"
    while True:
        events = await run_in_threadpool(store.list_events, run_id, seq)
        for event in events:
            seq = event.seq
            yield f"id: {event.seq}\ndata: {json.dumps(event.model_dump(mode='json'))}\n\n"
            if event.kind in TERMINAL_STATUSES:
                return
        run = await run_in_threadpool(store.get_run, run_id)
        if run is None or run.status in TERMINAL_STATUSES:
            # Finished without a terminal event (e.g. purged, or failed out-of-band).
            return
        now = loop.time()
        if now - started > SSE_MAX_S:
            return  # the client reconnects with Last-Event-ID
        if now - last_ping > SSE_KEEPALIVE_S:
            last_ping = now
            yield ": keepalive\n\n"
        await asyncio.sleep(SSE_POLL_S)


app = create_app()
