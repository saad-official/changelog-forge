# Changelog Forge — product and technical spec

Status: approved 2026-10-04. Level 1 project of the [AI Engineering Journey](https://github.com/saad-official/ai-engineering-journey) (Phase 1: LLM API fundamentals), built as a deployed product in the Vibe Build Series (batch 3, app 7). The 12-question evaluation lives in the journey's `PROJECTS.md`; this file is the build contract.

## 1. Problem

Release notes are tedious, skipped, or low quality. Commit messages and PR titles contain the facts but not the narrative, and nobody reads 200 commits. Maintainers want two things from one run: notes a user can read ("What's New") and notes a developer can act on (breaking changes, migration steps, every PR linked).

## 2. Users

Open-source maintainers, small product teams, indie developers publishing app updates. Demo audience: anyone with a public GitHub repo.

## 3. What it does (MVP for this build)

Input: a public GitHub repository plus a range (`base..head`: tags, branches or SHAs) or a GitHub compare URL. Output: release notes for two audiences, each categorised (Features, Fixes, Breaking changes, Performance, Docs, Internal), with every item linked to its source commit or PR, breaking-change detection with a confidence, and a JSON form of the same data.

Interfaces:
1. **Web app** (Next.js): paste repo + range, watch progress stream (collecting, grouping, drafting N of M, merging), read the two documents side by side, copy as Markdown, download JSON, see the cost of the run in tokens and dollars at paid rates.
2. **CLI** (`changelog-forge owner/repo v1.2.0..v1.3.0 --audience user,dev`): prints Markdown, `--json`, `--out`.
3. **HTTP API** (FastAPI): same engine, used by the web app and the Action.
4. **GitHub Action** (`saad-official/changelog-forge@v1`): on a tag or release PR, generates notes and posts them as a PR comment or release body. Uses the public API or runs the CLI in-container.

Not in MVP: private repos through OAuth (a personal token can be pasted per run and is never stored), translations, App Store / Play Console publishing, multi-tenant accounts, billing.

## 4. Pipeline (the AI architecture)

```
collect  -> normalise -> chunk -> map (cheap model) -> reduce (better model) -> verify -> render
GitHub      ChangeItem   token-     Change[] per        prose per audience     links,     Markdown
REST        (commit, PR, aware      group: category,    + merged item list     SHAs, PR   + JSON
            author,      groups     summary, breaking?,                        numbers
            files, url)             confidence, refs                           exist
```

- **collect**: `GET /repos/{o}/{r}/compare/{base}...{head}` (paginated, up to 400 commits per run; more is rejected with a clear message), plus PR lookup per commit via `GET /repos/{o}/{r}/commits/{sha}/pulls`; unauthenticated 60 req/h, so a server `GITHUB_TOKEN` (5,000 req/h) is used when set and a per-run user token overrides it. Everything is cached by `(repo, sha)` in Postgres so re-runs only pay for new commits.
- **normalise**: merge commits and PR-squash commits become one `ChangeItem` carrying the PR title, body (first 1,500 chars), labels, files touched, and the conventional-commit type when present.
- **chunk**: token-aware groups (target 6,000 input tokens; count with `tiktoken` `o200k_base` as an approximation, record the provider's reported usage afterwards) that never split a PR's commits across groups.
- **map**: for each group, `complete_structured(GroupAnalysis)` on the cheap tier (Groq `openai/gpt-oss-20b`): each item gets `category`, `user_summary`, `dev_summary`, `breaking: bool`, `breaking_confidence 0-1`, `migration_note | null`, `refs: [sha | #pr]`. The prompt forbids inventing PR numbers or SHAs; anything not in the input is dropped by the verifier.
- **reduce**: on the capable tier (Groq `openai/gpt-oss-120b` if available on the free tier, otherwise Gemini `gemini-3.5-flash-lite`): dedupe related items, order by importance, write the per-audience intro paragraph and section prose. Two reduce calls (user, dev) share the merged item list, so the two documents never disagree about facts.
- **verify** (deterministic): every referenced SHA and PR number must exist in the collected set; every item must keep at least one link; breaking items need `breaking_confidence >= 0.6` or they are downgraded to "possibly breaking" in the dev doc and omitted from the user doc; length budget per section.
- **render**: Markdown (GitHub flavoured, links as `[#123](url)` / `[abc1234](url)`) and JSON (`ReleaseNotes` model).

Model routing is a config table (`routing.toml`): `map` tier, `reduce` tier, fallbacks, max tokens, temperature 0.2. Every call goes through `llm_kit.LLM` with a per-run `Ledger(max_usd=0.05)`; the ledger summary is returned to the UI. Prompts are versioned files under `prompts/<name>.v1.md` and their version string is stored on each run.

## 5. Data model (Postgres on Neon, schema `changelog_forge`)

```
repos(id, owner, name, default_branch, fetched_at)
commits(repo_id, sha, author, date, message, pr_number, pr_title, pr_body, labels jsonb, files jsonb) — cache, PK (repo_id, sha)
runs(id, repo_id, base, head, status: queued|collecting|mapping|reducing|verifying|done|failed, audiences text[],
     commit_count, group_count, prompt_versions jsonb, routing jsonb, usage jsonb (tokens, usd), error, created_at, finished_at)
run_events(run_id, seq, at, kind, message, data jsonb)         — progress stream, append-only
run_outputs(run_id, audience, markdown, json jsonb, verified jsonb (dropped refs, downgraded items))
eval_runs(id, golden_set_version, scores jsonb, created_at)    — results of the eval harness
```

No accounts in MVP. Rate limit: 10 runs per hour per IP (in-process token bucket plus a Postgres count). Runs older than 30 days are purged by a daily job.

## 6. API (FastAPI, `/api`)

- `POST /api/runs` `{ repo: "owner/name" | compare_url, base, head, audiences: ["user","dev"], github_token?: string }` → `202 { id, status }`. Validates the repo is public (or the token can read it), collects synchronously up to the commit cap, then runs the pipeline in a background task.
- `GET /api/runs/{id}` → `{ id, status, repo, base, head, commit_count, group_count, usage, outputs: { user: { markdown, json }, dev: {...} }, verified, error }`.
- `GET /api/runs/{id}/events` → Server-Sent Events of `run_events` (replays history then tails until `done|failed`).
- `GET /api/runs/{id}.md?audience=user` → `text/markdown` download.
- `GET /api/health` → `{ ok, version, providers: { groq: bool, gemini: bool }, db: bool }`.
- `POST /api/evals/run` (bearer `CRON_SECRET`) → runs the golden set, stores `eval_runs`.

OpenAPI at `/api/docs`.

## 7. Evaluation (`evals/`)

Golden set of 10 public ranges (real repos, e.g. a small range of `expo/expo`, `vercel/ai`, `fastapi/fastapi`, `pydantic/pydantic`, `shadcn-ui/ui`, `drizzle-team/drizzle-orm`, `vitest-dev/vitest`, `tailwindlabs/tailwindcss`, `honojs/hono`, `withastro/astro`), each with a hand-curated `expected.json`: must-mention items (by PR number), must-flag breaking changes, forbidden claims. Collected inputs are snapshotted into the repo so evals are deterministic and free of GitHub rate limits.

Code-based scorers: coverage of expected items (recall), hallucinated references (any SHA/PR not in input: must be 0), breaking-change recall and precision, category accuracy against labels, link validity, length budget, JSON schema validity. LLM-judge only for prose quality with a 1-5 rubric, reported separately. `uv run evals` prints a table and writes `docs/evals.md` with the latest numbers; CI runs the deterministic scorers against recorded model outputs (no network) and the live suite is manual.

## 8. Costs (`docs/costs.md`)

Measured by the ledger: tokens and dollars at paid rates per run, per 100 commits, by model. Target: under $0.01 per 100 commits. The free tiers cover development and the demo; the doc states what a paid month would cost at 100 runs/day.

## 9. Hosting (all free)

- API: Docker image (`python:3.12-slim`, `uv sync --frozen`, `uvicorn` on `$PORT`, default 7860) deployable to Hugging Face Spaces (Docker) or Render free; the research note in `docs/decisions/0002-hosting.md` records the pick. Health endpoint for keep-alive.
- Web: Next.js 16 on Vercel Hobby (`web/`), calling the API with `NEXT_PUBLIC_API_URL`.
- Database: Neon Free project `changelog-forge`, schema `changelog_forge`, migrations with plain SQL files applied by `uv run migrate`.
- Observability: Langfuse Cloud free (optional, `LANGFUSE_*` env) through llm-kit's call records; always-on structured logs.
- GitHub Action: `action.yml` in this repo, Docker-based, calls the CLI.

## 10. Identity

Dev-tool calm: paper and graphite with three semantic colours that mean something in a changelog: **release green** (features), **signal amber** (fixes/perf), **breaking red** (breaking changes). Type: **Archivo** (headings, tight), **Public Sans** (body), **Red Hat Mono** (SHAs, PR numbers, counts). The two audience documents sit side by side; every item shows its source link chips; the progress stream reads like a terminal log. No gradient hero.

## 11. Learning artefacts (journey rules)

- Concept notes to draft or update in the journey repo: structured-outputs, provider-abstraction, cost-and-latency-basics, prompt-versioning, hallucination-and-grounding (the verifier), map-reduce as a pattern (new note `chunk-and-merge.md`).
- `docs/decisions/0001-model-routing.md`, `0002-hosting.md`, `0003-verification-over-trust.md`.
- `docs/architecture.md` with the data-flow diagram and failure modes (rate limits, partial failures, truncated outputs).
- "Explain it back" questions at the end of the README (why routing, why verify, why cache by SHA, why ledger at paid rates).

## 12. Tests

Normaliser (merge/squash detection, conventional-commit parsing), chunker (never splits a PR, respects token budget), verifier (drops unknown refs, downgrades low-confidence breaking), renderer (links, sections), API (runs lifecycle with a fake pipeline), evals scorers (on fixtures), CLI argument parsing. Model calls are stubbed in tests; one live smoke script exists for manual use.
