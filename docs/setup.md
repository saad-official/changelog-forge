# Setup

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 for the project from
  `.python-version`; the system Python is not used).
- A Groq API key (free tier) and, optionally, a Gemini key for the fallback tier.
- Optional: a GitHub token (raises GitHub's limit from 60 to 5,000 requests/hour), a Neon
  Postgres database, an Upstash QStash token.

## Local development

```powershell
uv sync                         # creates .venv, installs runtime + dev dependencies
Copy-Item .env.example .env     # then fill in GROQ_API_KEY (and GEMINI_API_KEY)

uv run ruff check . ; uv run ruff format --check . ; uv run pytest -q
uv run evals                    # golden set against recorded model outputs (no network)
```

Developing llm-kit at the same time (see [0004](decisions/0004-llm-kit-dependency.md)):

```powershell
uv run --with-editable ../../packages/llm-kit pytest -q
```

## CLI

```powershell
uv run changelog-forge honojs/hono v4.13.10..v4.13.13 --audience user,dev
uv run changelog-forge https://github.com/honojs/hono/compare/v4.13.10...v4.13.13 --json --out notes.json
uv run changelog-forge honojs/hono v4.13.10..v4.13.13 --token $env:GITHUB_TOKEN   # per-run token
```

Installed as a tool: `uv tool install git+https://github.com/saad-official/changelog-forge`,
with `GROQ_API_KEY`, `GEMINI_API_KEY` (optional) and `GITHUB_TOKEN` (optional) exported.
Progress and the cost ledger go to stderr; exit codes: 2 bad arguments, 3 GitHub error.

## API

```powershell
uv run uvicorn changelog_forge.api.main:app --port 7860 --reload
# http://localhost:7860/api/docs
```

Without `DATABASE_URL` the API uses an in-memory store and runs the pipeline as a
background task after `POST /api/runs` returns. With Postgres:

```powershell
# .env: DATABASE_URL=postgresql://…@…-pooler…neon.tech/neondb?sslmode=require
uv run migrate                  # applies src/changelog_forge/db/migrations/*.sql once each
uv run purge                    # deletes runs older than 30 days (also POST /api/cron/purge)
```

The web app (`web/`) talks to the API at `NEXT_PUBLIC_API_URL`; add its origin to
`WEB_ORIGIN`.

## Deploy: Vercel (primary)

See [0002-hosting.md](decisions/0002-hosting.md). The repository root is a Vercel project
(`main.py` re-exports the FastAPI app, `vercel.json` selects the `fastapi` preset;
dependencies come from `pyproject.toml`/`uv.lock`). `web/` is a second Vercel project with
root directory `web`.

Environment (Production): `GROQ_API_KEY`, `GEMINI_API_KEY`, `GITHUB_TOKEN`,
`DATABASE_URL` (**required** on Vercel: instances do not share memory), `WEB_ORIGIN`,
`CRON_SECRET`, `IP_HASH_SALT`, and optionally `PUBLIC_API_URL` + `QSTASH_TOKEN` +
`QSTASH_CURRENT_SIGNING_KEY` + `QSTASH_NEXT_SIGNING_KEY` (then QStash triggers
`/process`), `LANGFUSE_*`. Vercel sets `VERCEL=1`, which switches dispatch to `client` when
QStash is absent and trusts `X-Forwarded-For` for rate limiting.

Daily purge on the Hobby cron (one job per day) - add to `vercel.json` when deploying:

```json
{ "crons": [ { "path": "/api/cron/purge", "schedule": "0 4 * * *" } ] }
```

## Deploy: Docker (Render or anywhere)

```powershell
docker build -t changelog-forge .
docker run -p 7860:7860 --env-file .env changelog-forge
```

The image (`python:3.12-slim`, non-root, `uv sync --frozen --no-dev`, tiktoken encoding
pre-fetched, healthcheck on `/api/health`) builds from this repository alone. On Render,
use a Docker web service; `PORT` is honoured.

## GitHub Action

See the README section "GitHub Action". The action runs this same image with
`action/entrypoint.sh` as the entrypoint (in-memory store, no database).

## Live smoke test

```powershell
uv run python scripts/smoke_live.py                         # honojs/hono v4.13.10..v4.13.13
uv run python scripts/smoke_live.py fastapi/fastapi 0.142.0..0.142.2
```

Real GitHub, real models; prints the ledger and writes `runs/smoke-*/` (gitignored).
