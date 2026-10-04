# Architecture

How a git range becomes two verified documents, where state lives, and what happens when
something fails. The build contract is [spec.md](spec.md); the decisions are in
[decisions/](decisions/).

## Data flow

```
                    POST /api/runs (sync, < ~30 s)                 POST /api/runs/{id}/process (<= 250 s, resumable)
                    ───────────────────────────────                ─────────────────────────────────────────────────
 owner/repo  ─▶ refs.resolve_target ─▶ collect.github ─▶ checkpoint "collected"
 base..head        (parse, validate)   compare + PR lookups          │
 compare URL                           (cache by repo+sha, ETag)     ▼
                                                            normalise ─▶ chunk ─▶ map (per group) ─▶ verify refs ─▶ reduce dev ─▶ dedupe ─▶ reduce user ─▶ verify budgets ─▶ render
                                                            ChangeItem   ~4.5k-token  GroupAnalysis      MergedItem[]    DevDraft      apply      UserDraft      trims, breaking    Markdown + JSON
                                                            (PR-folded)  groups     cheap tier         (shared facts)  capable tier  dup groups capable tier   threshold          per audience
                                                                                    checkpoint map:N                   checkpoint                 checkpoint
```

| Stage | Module | Model? | Output | Notes |
|---|---|---|---|---|
| collect | `collect/github.py` | no | `CollectedRange` | compare (100/page, cap 400), `commits/{sha}/pulls` per uncached commit, files only when authenticated |
| normalise | `normalise.py` | no | `ChangeItem[]` | merge and squash commits folded into their PR; conventional-commit parsing; PR body cleaned and cut to 1,500 chars |
| chunk | `chunk.py` | no | groups | greedy, order-preserving, `tiktoken` `o200k_base`, target 4,500 tokens (configurable; see `routing.toml` `[chunk]`); a PR is one item, so it is never split |
| map | `pipeline/map.py` | cheap tier | `GroupAnalysis` | strict JSON schema; category, two summaries, breaking + confidence, migration, refs |
| verify (refs) | `pipeline/verify.py` | no | `MergedItem[]` | unknown refs dropped, sha prefixes and bare numbers canonicalised, uncovered inputs get fallback items |
| reduce | `pipeline/reduce.py` | capable tier | `DevDraft`, `UserDraft` | editorial only: intro, order, section prose, duplicate groups (dev call) |
| verify (docs) | `pipeline/verify.py` | no | placement, budgets | breaking needs confidence >= 0.6; reducer cannot move or invent items; length budgets |
| render | `pipeline/render.py` | no | `ReleaseNotes`, Markdown | JSON first, Markdown rendered from it; `@mentions` neutralised, HTML escaped |

Why both documents agree: the reducer never rewrites item text. Both documents are rendered
from one verified `MergedItem` list (the user one is a filtered view of it). The models can
differ in tone between the two intros; they cannot differ in what changed.

## Components

```
            ┌──────────── web/ (Next.js, Vercel project 1) ───────────┐
            │ form ─▶ POST /api/runs ─▶ POST /process ─▶ EventSource   │
            └───────────────────────────┬─────────────────────────────┘
                                        │ HTTPS + CORS (WEB_ORIGIN)
┌──────────── API (FastAPI; Vercel Python runtime, or Docker on Render) ───────────┐
│ api/main.py ── service.RunService ── pipeline.Pipeline ── llm.RoutedLLM ── llm-kit │──▶ Groq / Gemini
│      │               │                                                             │
│      │               └── collect.GitHubClient ─────────────────────────────────────│──▶ api.github.com
│      └── db.Store (PostgresStore | MemoryStore) ───────────────────────────────────│──▶ Neon Postgres
└────────────────────────────────────────────────────────────────────────────────────┘
       ▲ QStash (optional) POSTs /process, signed         ▲ Vercel Cron: /api/cron/purge, /api/evals/run
```

`Engine` (`engine.py`) wires settings, routing and the store into factories for the GitHub
client and the two model tiers; tests swap the factories for fakes. The CLI, the API, the
evals and the GitHub Action all drive the same `Pipeline`.

## Run state machine

```
            create_run (POST /api/runs)
  (none) ──────────────▶ collecting ──GitHub error──▶ failed  (4xx returned to the caller)
                             │ collected input checkpointed
                             ▼
                          queued ◀─────────────── time budget hit: lease released,
                             │ claim (lease ~270 s)  attempt given back, resumable: true
                             ▼                                 ▲
                          mapping ──▶ reducing ──▶ verifying ──┴──▶ done
                             │            │            │
                             └────────────┴────────────┴── unexpected error ──▶ failed
             lease expired (request killed) ─▶ claimable again, resumes from checkpoints;
             3 attempts that ended without finishing ─▶ failed ("gave up after 3 attempts")
```

- **Claim** is one atomic `UPDATE ... WHERE lease_until IS NULL OR lease_until <= now()`
  (`PostgresStore.claim_run`), so two `/process` calls cannot both run a stage. The loser
  gets `409 run_in_progress`.
- **Checkpoints** (`run_checkpoints`): `collected`, `groups`, `map:1..N`, `reduce:dev`,
  `reduce:user`, `models:*`, and `ledger` (every call record so far). A resumed attempt
  skips finished stages and keeps counting cost from where it stopped, so the $0.05 ceiling
  is per run, not per request.
- **Events** (`run_events`) are append-only with a per-run `seq`; SSE replays from
  `Last-Event-ID` and polls Postgres every 0.5 s, so any instance can serve any run's stream.

## Failure modes

| Failure | Where | Behaviour |
|---|---|---|
| Repo missing or private without token | collect | `404 repo_not_found` on POST; run recorded as failed |
| Ref missing | collect | `404 range_not_found` |
| More than 400 commits | collect | `422 commit_cap` before any PR lookup |
| GitHub rate limit | collect | `429 rate_limited` with `Retry-After` from `x-ratelimit-reset`; **pre-flight**: after the compare call the client knows how many lookups remain and refuses up front instead of failing at commit 57 |
| Groq 429 / 5xx | map, reduce | llm-kit retries with jittered backoff (3 attempts, 45 s deadline), then `RoutedLLM` falls back to Gemini |
| Groq 413: one request above the 8K TPM limit | map | not retryable; prevented by 4,500-token groups (a 6,000-token group arrived as 8,040 tokens on the first eval) |
| Groq daily token quota (200K TPD) exhausted | map, reduce | the 429 is retried once by llm-kit's loop (~42 s), then the route is parked until the quota resets and later calls go straight to the fallback |
| Groq 400 "does not match the expected schema" | map, reduce | one resample on the same route (`schema_retries`), then fallback. Seen on the first live run |
| Output fails Pydantic validation | map, reduce | llm-kit repairs once, then fallback route |
| Truncated output (`finish_reason=length`) | map, reduce | reported as truncation by llm-kit (not "bad JSON"), then fallback; map `max_tokens` is 8,192 because gpt-oss spends hidden reasoning tokens |
| Every route fails for a map group | map | deterministic fallback items for that group (PR title, category from labels / conventional type); recorded in `verified.degraded` and as a `warning` event |
| Cost ceiling reached ($0.05) | any | `LLMBudgetError` is never fallen back from; remaining map groups become fallback items; reduce uses the template draft |
| Every route fails for reduce | reduce | template intro (counts per section), input order; recorded |
| Model cites a PR/SHA not in the range | verify | dropped, listed in `verified.dropped_refs`; an item left with no refs is dropped; any input left uncovered gets a fallback item |
| Model skips an input | verify | fallback item, listed in `verified.uncovered_inputs` |
| Reducer invents or moves items | verify | unknown ids ignored and recorded; placement always comes from the item's own facts |
| Request killed at the platform limit | process | lease expires, next `/process` resumes from checkpoints |
| Time budget reached mid-run | process | `202 {resumable: true}`; call `/process` again |
| Prompt injection in a PR body | map | repository text is delimited (`<repository_content>`), closing tags escaped, prompts say to ignore instructions inside; worst case is a wrong summary, which still cannot cite refs outside the range |
| Langfuse down | after run | logged and ignored |

## Why psycopg 3 (sync) and a `Store` protocol

llm-kit is synchronous, so the pipeline runs in a worker thread (FastAPI's threadpool).
psycopg 3's sync API is callable from that thread directly; asyncpg is async-only and every
checkpoint write would have to hop back onto the event loop. psycopg also exposes
`prepare_threshold=None`, which Neon's pooled (PgBouncer, transaction mode) endpoint needs.
At a few queries per second, driver throughput is irrelevant.

The `Store` protocol (`db/store.py`) has two implementations with the same semantics:
`PostgresStore` for deploys and `MemoryStore` for tests, the CLI and the GitHub Action. The
API tests run every route against `MemoryStore`; one Postgres test runs when
`TEST_DATABASE_URL` is set.

## Security notes

- A per-run GitHub token is used for collection inside the POST request and never stored
  or logged (`/process` never calls GitHub: it reads the checkpointed input). Private-repo
  commits are not written to the shared `(repo, sha)` cache.
- Client IPs are stored only as salted SHA-256 hashes (`runs.client_key`).
- QStash deliveries are verified (HS256 JWT: issuer, subject URL, expiry, body hash) with
  the current and next signing keys.
- Cron endpoints need `Authorization: Bearer $CRON_SECRET`.
- Release notes never ping people: `@name` is rendered as code.
