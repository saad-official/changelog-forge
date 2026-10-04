# 0001 — Model routing: a cheap tier for map, a capable tier for reduce

Date: 2026-10-04. Status: accepted. Config: [`routing.toml`](../../src/changelog_forge/routing.toml).

## Context

A run makes two kinds of model calls with very different shapes:

- **map**: one call per ~6,000-token group. Classify each change, write two one-sentence
  summaries, judge "breaking" with a confidence, cite refs. Many calls, small structured
  outputs, low stakes per call (the verifier catches bad refs; a bad summary affects one
  bullet).
- **reduce**: two calls per run over the whole verified item list. Order by importance, spot
  duplicates, write the intro and section prose a human reads first. Few calls, larger
  context, the most visible text.

Spending capable-model prices on map calls buys little; spending cheap-model quality on the
intro is the thing users notice. Prices at paid rates (llm-kit `pricing.py`, verified
2026-09-05, USD per 1M tokens in/out): `openai/gpt-oss-20b` 0.075/0.30,
`openai/gpt-oss-120b` 0.15/0.60, `gemini-3.5-flash-lite` 0.30/2.50.

Free-tier limits confirmed 2026-10-04 for both Groq models: 30 RPM, 8,000 TPM, 1,000 RPD.

## Decision

| Tier | Primary | Fallback | max_tokens | Notes |
|---|---|---|---|---|
| map | Groq `openai/gpt-oss-20b`, `reasoning_effort=low` | Gemini `gemini-3.5-flash-lite` | 8,192 | 4,500-token groups; one same-route resample on a strict-schema rejection, then fallback |
| reduce | Groq `openai/gpt-oss-120b`, `reasoning_effort=low` | Gemini `gemini-3.5-flash-lite` | 6,144 | dev call (with dedupe) first, then user call |

Temperature 0.2 everywhere. Per-run ledger ceiling $0.05. Retry: 3 attempts, 45 s
deadline (shorter than llm-kit's default because a serverless request has ~250 s).

Routing is a TOML table, not code, so a model swap is a one-line reviewed diff, and every
run stores the routing it used (`runs.routing`, with `served_by` per tier). A test asserts
every routed model has a price in llm-kit, because an unpriced model would be costed at the
worst known rate.

Two pieces of routing logic live in the project's adapter (`llm.py`) rather than llm-kit,
because they are about this project's problem, not about providers:

- **Fallback across providers** on transient errors past the retry deadline, permanent
  errors (a withdrawn model id), output errors after the repair attempt, and a missing key.
  Never on `LLMBudgetError`: that is our own ceiling doing its job.
- **Tokens-per-minute pacing.** llm-kit paces by requests per minute; Groq's free tier also
  caps tokens per minute. One 6,000-token group plus its output nearly fills a minute, so
  the pacer keeps a sliding 60-second window per model (fed by the Ledger's records after
  every call) and sleeps before a call that would overflow it.

## Evidence (first live runs, 2026-10-04)

- Smoke run 1 (honojs/hono, 20 commits): gpt-oss-20b produced a category outside the enum;
  Groq rejected it server-side with a 400 ("Generated JSON does not match the expected
  schema"), llm-kit correctly classified a 400 as permanent, and the router fell back to
  Gemini. Result: correct notes, but $0.040 per 100 commits, 4x over target, because Gemini
  flash-lite output costs 8x gpt-oss-20b output.
- Fix: tighter category wording in `map.v1.md` plus `schema_retries = 1` (resample once on
  the cheap route before falling back). Smoke run 2, same range: served by gpt-oss-20b,
  **$0.0018 for 20 commits = $0.009 per 100 commits**, under the $0.01 target.
- Live golden-set runs (10 repos, 267 commits) found two more causes of expensive
  fallbacks. (1) The spec's 6,000-token groups plus the ~900-token system prompt reached
  Groq as 8,040 tokens: a single request above the 8K TPM limit is rejected outright (413),
  so those groups always fell back. Groups are now 4,500 tokens (`[chunk]` in
  `routing.toml`), and a test pins the limit. (2) gpt-oss-20b's free tier also has a 200K
  tokens-per-day quota; after a day of development it ran out, and llm-kit retried each
  call for ~42 s before falling back. The router now parks a route whose daily quota is
  exhausted until the reset time. Second run: all 10 cases pass the gates; 5 of 28 map
  calls (quota) on Gemini cost 54% of the run; Groq-only projection ~$0.009 per 100 commits.
- See [costs.md](../costs.md) and [evals.md](../evals.md) for the full numbers.

## Alternatives considered

1. **One model for everything (gpt-oss-120b).** Simpler; roughly 2x the map cost and the
   same 8K TPM ceiling, so no faster. Rejected: the map step does not need it.
2. **Gemini flash-lite primary.** Generous free tier and no TPM pacing pain, but output
   tokens cost 8x gpt-oss-20b at paid rates, and free-tier prompts are used for training
   (fine for public repos, not for private ones). Kept as the fallback.
3. **A local model (Ollama) for map.** Zero marginal dollars, but 4-7 tok/s on the dev
   machine; a 64-PR range would take many minutes per group. Not viable for a hosted demo.

## Consequences

- Free-tier throughput is bounded by 8K TPM: a 400-commit range is ~15 map groups, so
  about 12-15 minutes of pacing on Groq alone. That run spans several `/process` calls
  (each ~250 s, resumable from checkpoints) or uses QStash.
- Model choice is measurable: `uv run evals --live` re-scores the golden set after any
  routing change, and the cost per 100 commits is in `docs/evals.md`.
