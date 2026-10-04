# 0002 — Hosting the Python API on Vercel's Python runtime

Date: 2026-10-04. Status: accepted.

## Context

Every service must stay on a free plan. A research pass on 2026-10-04 (see the series repo, `research/research-ai-batch3-free-tiers.md`) found that the usual free homes for a Dockerised FastAPI service have closed or changed:

- Hugging Face Spaces: Docker and Gradio Spaces on CPU Basic now require PRO; only static Spaces are free.
- Koyeb: free tier closed to new users (Feb 2026). Fly.io: no free tier. Railway: trial credit only.
- Google Cloud Run: generous always-free quota, but a billing account (card) is mandatory.
- Render free: no card, but 512 MB RAM, spins down after 15 minutes idle and wakes in about a minute; 750 instance-hours per workspace per month, so only one service can be kept warm.

A spike the same day deployed a FastAPI app to Vercel's Python runtime on the Hobby plan: a root-level `main.py` exporting `app` with `vercel.json` `{ "framework": "fastapi" }` preserved request paths, served Server-Sent Events, and answered in about one second from cold. Hobby functions may run up to 300 seconds (Fluid compute) with a 250 MB bundle limit and a 4.5 MB request body limit.

## Options

1. **Vercel Python runtime** (chosen). Free, already signed in, no sleeping, same platform as the UI. No long-lived workers: background work must finish inside a request (≤ 300 s) or be driven by an external queue.
2. Render free with a GitHub Actions keep-alive ping. Free and Docker-based, but a one-minute wake for anything not pinged, and only one warm service across the three apps.
3. Cloud Run. Technically the best fit for Docker, but requires a card, which the series rules out.

## Decision

Deploy the API to Vercel's Python runtime from the repository root (`main.py`, `vercel.json` with the `fastapi` framework preset, dependencies from `pyproject.toml`). The Next.js app deploys as a separate Vercel project with root directory `web/`. Pipeline work runs in a dedicated `POST /api/runs/{id}/process` request (idempotent, resumable per stage, under 250 s); it is triggered through Upstash QStash when `QSTASH_TOKEN` is configured, otherwise by the client after creating the run. The Dockerfile stays in the repo so the same service can move to Render or Cloud Run without code changes.

## Consequences

- No in-process background workers or cron. Daily maintenance runs through Vercel's Hobby cron (once a day) or GitHub Actions.
- Runs over the commit cap (400) or the time budget are rejected up front with a clear message rather than left half-finished.
- Cold starts are about one second, so the UI needs no "waking up" state.
- The `llm-kit` dependency is installed from the journey repository as a git source pinned to a commit (see 0004), because Vercel builds from this repository alone.
