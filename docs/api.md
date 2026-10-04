# HTTP API

Interactive reference: **`/api/docs`** (OpenAPI 3, generated from the Pydantic models in
[`api/schemas.py`](../src/changelog_forge/api/schemas.py); raw schema at
`/api/openapi.json`). This page is the contract summary the web app and the GitHub Action
rely on.

## Flow

```
POST /api/runs                      -> 202 {id, status: "queued", process, process_url, events_url}
POST /api/runs/{id}/process         -> 200 {status: "done"|"failed"} | 202 {resumable: true} | 409
GET  /api/runs/{id}/events          -> text/event-stream (replay, then tail until done|failed)
GET  /api/runs/{id}                 -> the run: status, usage, outputs, verified
GET  /api/runs/{id}.md?audience=dev -> text/markdown attachment
```

`process` in the create response says who runs the pipeline:

- `"background"` (local, Docker): the API already started it after the 202.
- `"qstash"`: Upstash QStash will POST `/process` (signed); the client just follows events.
- `"client"` (Vercel without QStash): the client must `POST process_url` itself.

`/process` is idempotent: calling it while another request holds the run's lease returns
`409 run_in_progress` (progress still arrives over SSE); calling it after the run finished
returns `200` with the final status. A lease lasts ~270 s, so a request that died is taken
over by the next call, which resumes from the last checkpoint. **`202` with
`resumable: true` means the request's time budget ran out mid-run: POST `/process` again**
(large ranges on the Groq free tier need several calls; QStash retries do this for you).

## Endpoints

### `POST /api/runs`

```json
{ "repo": "honojs/hono", "base": "v4.13.10", "head": "v4.13.13",
  "audiences": ["user", "dev"], "github_token": "optional, this run only, never stored" }
```

`repo` may also be a compare URL (`https://github.com/o/r/compare/a...b`), with or without
`base`/`head`. Collection happens inside this request (up to the 400-commit cap), so
GitHub problems are returned here. Rate limit: 10 runs per hour per client IP.

### `GET /api/runs/{id}`

```jsonc
{
  "id": "…", "status": "done", "repo": "honojs/hono", "base": "v4.13.10", "head": "v4.13.13",
  "audiences": ["user", "dev"], "commit_count": 20, "group_count": 1,
  "created_at": "…", "finished_at": "…", "error": null,
  "prompt_versions": { "map": "map.v1@1a2b3c4d", "reduce_dev": "…", "reduce_user": "…" },
  "routing": { "version": "2026-10-04", "tiers": { "map": ["groq:openai/gpt-oss-20b", "gemini:gemini-3.5-flash-lite"] }, "served_by": { "map": "openai/gpt-oss-20b" } },
  "usage": {
    "calls": 3, "failed_calls": 0, "prompt_tokens": 6554, "completion_tokens": 2916,
    "reasoning_tokens": 1202, "total_tokens": 9470, "usd": 0.001791, "max_usd": 0.05,
    "by_model": [ { "model": "openai/gpt-oss-20b", "provider": "groq", "stage": "map",
                    "calls": 1, "prompt_tokens": 4100, "completion_tokens": 2100,
                    "reasoning_tokens": 900, "usd": 0.000938 } ],
    "summary": "3 calls  6554 in / 2916 out …", "prices_verified_on": "2026-09-05"
  },
  "outputs": {
    "user": { "markdown": "## What's new in …", "json": { /* ReleaseNotes */ } },
    "dev":  { "markdown": "…", "json": { /* ReleaseNotes */ } }
  },
  "verified": {
    "checked_refs": 20,
    "dropped_refs": [ { "ref": "#4242", "stage": "map", "reason": "PR #4242 is not in the collected range" } ],
    "dropped_items": [], "uncovered_inputs": [], "unknown_item_ids": [],
    "downgraded": [ { "item_id": "i7", "summary": "…", "refs": [ { "kind": "pr", "id": "#5221", "url": "…" } ],
                      "breaking_confidence": 0.5, "reason": "breaking confidence 0.50 is below 0.6 …" } ],
    "trimmed": [], "clamped": [], "degraded": []
  }
}
```

`ReleaseNotes` (`outputs.*.json`):

```jsonc
{ "schema_version": "1", "audience": "dev", "repo": "…", "base": "…", "head": "…",
  "title": "…", "intro": "…", "compare_url": "…", "commit_count": 20, "generated_at": "…",
  "prompt_versions": {…}, "models": { "map": "openai/gpt-oss-20b", "reduce": "openai/gpt-oss-120b" },
  "sections": [
    { "category": "breaking" | "possibly_breaking" | "feature" | "fix" | "performance" | "docs" | "internal",
      "title": "Breaking changes", "prose": "…" | null,
      "items": [ { "id": "i1", "category": "feature", "summary": "…",
                   "breaking": false, "possibly_breaking": false, "breaking_confidence": 0.0,
                   "migration_note": null, "source": "model" | "fallback",
                   "refs": [ { "kind": "pr", "id": "#5221", "url": "https://github.com/…/pull/5221", "number": 5221, "sha": null },
                             { "kind": "commit", "id": "8b05c77", "url": "https://github.com/…/commit/8b05c77…", "number": null, "sha": "8b05c77…" } ] } ] } ] }
```

The user document contains `breaking`, `feature`, `fix`, `performance`; the developer
document adds `possibly_breaking`, `docs`, `internal`.

### `GET /api/runs/{id}/events`

Server-Sent Events, **unnamed** (`onmessage` receives everything), each with `id: <seq>`:

```
retry: 2000

id: 4
data: {"run_id":"…","seq":4,"at":"2026-10-04T17:15:22Z","kind":"progress","message":"Drafting group 1 of 2 (31 changes)","data":{"level":"info","stage":"mapping","group":1,"groups":2}}
```

`kind`: `status` (with `data.status`), `progress`, `warning` (`data.level: "warn"`),
`done`, `failed` (`data.level: "error"`). Useful `data` fields: `status`, `stage`,
`commit_count`, `group_count`, `group`, `groups`, `usage` (on `done`). The stream replays
history (or from `Last-Event-ID` / `?after=`), tails every 0.5 s, sends `: keepalive`
comments, closes after `done` or `failed`, and also closes after ~250 s (the browser
reconnects with `Last-Event-ID`).

### `GET /api/health`

`{ ok, version, providers: { groq, gemini }, db, store: "postgres"|"memory", dispatch }`.

### Cron (bearer `CRON_SECRET`; GET is accepted too because Vercel Cron sends GET)

- `POST /api/evals/run?mode=recorded|live&limit=N` runs the golden set and stores the
  report in `eval_runs`. Keep `limit` small for `live` on serverless.
- `POST /api/cron/purge` deletes runs older than 30 days.

## Errors

Every error is `{ "detail": { "code", "message", "retry_after"?, "field"? } }`
(request-validation errors keep FastAPI's default list shape).

| Status | `code` | When |
|---|---|---|
| 400 | `bad_request` | unparseable repo or range (`field`: `repo` or `range`) |
| 401 / 403 | `unauthorized` | GitHub rejected the token; bad QStash signature; wrong cron secret |
| 404 | `repo_not_found` | repository missing, or private without a token that can read it |
| 404 | `range_not_found` | a ref does not exist |
| 404 | `run_not_found` | unknown run id |
| 409 | `run_in_progress` | another `/process` call holds the run |
| 422 | `commit_cap` | more than 400 commits |
| 422 | `empty_range` | the range has no commits |
| 429 | `rate_limited` | 10 runs/hour exceeded, or GitHub's rate limit; `Retry-After` header and `retry_after` seconds |
| 502 | `github_error` | GitHub 5xx or unreachable |

CORS: origins from `WEB_ORIGIN` (comma-separated), `Retry-After` and `Content-Disposition`
exposed.
