# Costs

Every number here comes from llm-kit's `Ledger` (provider-reported token usage, priced at
**paid** rates from `llm_kit.pricing`, verified 2026-09-05), not from estimates. All runs
below actually ran on free tiers and cost $0.00; the point is what they would cost as real
traffic. Target from the spec: **under $0.01 per 100 commits**.

Prices (USD per 1M tokens, in / out): `openai/gpt-oss-20b` 0.075 / 0.30,
`openai/gpt-oss-120b` 0.15 / 0.60, `gemini-3.5-flash-lite` 0.30 / 2.50. Hidden reasoning
tokens are billed as output and are included in the output column.

## Measured runs (2026-10-04)

| Run | Commits | Calls | Tokens in / out (reasoning) | Cost | Per 100 commits | Served by |
|---|---|---|---|---|---|---|
| Smoke 1: `honojs/hono v4.13.10..v4.13.13` | 20 | 4 | 6,838 / 3,121 (316) | $0.008033 | $0.0402 | map fell back to Gemini (Groq rejected an off-schema category) |
| Smoke 2: same range, after the fix | 20 | 3 | 6,554 / 2,916 (1,202) | **$0.001791** | **$0.0090** | gpt-oss-20b map, gpt-oss-120b reduce; 40.6 s wall |
| Golden set, live (10 repos) | 267 | 48 | 127,000 / 35,156 (11,462) | $0.044507 | $0.0167 | 23 map calls on 20b, **5 on Gemini** (Groq daily quota hit), 20 reduce on 120b |
| Golden set, Groq-only projection | 267 | 48 | same tokens | ~$0.0244 | **~$0.0091** | the 5 Gemini map calls repriced at 20b rates |

Golden-set cost by model and stage (from the cassettes in `evals/golden/*/cassette.json`):

| Model | Stage | Calls | In | Out | Reasoning | Cost | Share |
|---|---|---|---|---|---|---|---|
| openai/gpt-oss-20b | map | 23 | 76,884 | 20,317 | 7,423 | $0.01186 | 27% |
| openai/gpt-oss-120b | reduce | 20 | 24,141 | 8,350 | 4,039 | $0.00863 | 19% |
| gemini-3.5-flash-lite | map (fallback) | 5 | 25,973 | 6,489 | 0 | $0.02401 | **54%** |

The LLM-judge calls (20 calls on the reduce tier, run with `--judge`) are excluded: they
measure prose quality, they are not part of a user's run.

## What the numbers say

- **Routing works when the cheap route serves.** On gpt-oss-20b + 120b a run costs about
  $0.009 per 100 commits, under the target. A 400-commit run (the cap) is about $0.036,
  under the $0.05 per-run ceiling.
- **Fallbacks are where the money goes.** Gemini flash-lite served 18% of map calls and
  cost 54% of the eval run, because its output tokens cost 8x gpt-oss-20b's. Every
  fallback in today's runs had a fixable cause, each now handled in `llm.py`:
  an off-schema enum value (one same-route resample before falling back), a 6,000-token
  group that reached Groq as 8,040 tokens and was rejected outright by the 8K TPM limit
  (groups are now 4,500 tokens), and the 200K tokens-per-day quota (the route is parked
  until the reset instead of burning ~42 s of retries per call).
- **Reasoning tokens are a real share.** A third of all output tokens in the eval run
  (40% of Groq's) were hidden reasoning, even at `reasoning_effort=low`. `max_tokens` stays high (8,192 for map)
  so reasoning cannot truncate the JSON.
- **Reduce is cheap.** Two calls per run on the better model add roughly 40% to a small
  run and much less to a large one, because their input is the compact verified item list,
  not the raw commits.

## Free-tier capacity (what limits a free deployment)

| Limit (Groq free, per model) | Value | What it means here |
|---|---|---|
| Tokens per minute | 8,000 | about one map group per minute: a 64-commit range (6 groups) takes ~6 minutes of pacing |
| Tokens per day | 200,000 (gpt-oss-20b) | ~28 map groups a day, roughly 250-300 commits of map work, then Gemini serves |
| Requests per day | 1,000 | not the binding limit |
| Requests per minute | 30 | not the binding limit |

So the free tier comfortably covers development and a demo (a few dozen runs of typical
patch releases a day), not a public launch.

## A paid month at 100 runs/day

Assumptions: an average run is 50 commits (patch and minor releases; the golden set
averages 27); routing as designed; 5% of map calls fall back to Gemini.

| Item | Per day | Per month (30 d) |
|---|---|---|
| Model tokens: 100 runs x 50 commits x $0.0091 / 100 commits | $0.46 | $13.65 |
| Fallback premium: 5% of map calls at ~6x the map price | ~$0.12 | ~$3.50 |
| **Models, total** | **~$0.58** | **~$17** |
| Groq paid tier (needed: 100 x ~5 groups x ~7.5K tokens = ~3.75M tokens/day >> 200K TPD) | | pay-as-you-go, included above |
| Vercel Hobby (API + web), Neon free, Upstash QStash free tier | $0 | $0 (within free limits at this volume) |

At a worst case of every map call on Gemini, models cost about $0.04 per 100 commits, so
about $60 a month for the same traffic. The routing table and the fallback rate are the
two levers; both are visible per run in `usage.by_model` and `routing.served_by`.

## How to reproduce

```powershell
uv run python scripts/smoke_live.py                 # one run, prints the ledger
uv run evals --live                                  # the golden set, writes docs/evals.md
uv run evals                                         # same numbers replayed from cassettes
```
