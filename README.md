# Changelog Forge

**A git range in, release notes for two audiences out.** Point Changelog Forge at a public GitHub repository and a range (`v1.2.0..v1.3.0`). It collects the commits and pull requests, groups them into token-sized batches, has a cheap model classify and summarise each batch into a strict schema, has a better model merge them into prose for end users and for developers, verifies every commit and PR reference against the input, and renders Markdown and JSON. Every run reports its token usage and cost at paid rates.

Level 1 project of the [AI Engineering Journey](https://github.com/saad-official/ai-engineering-journey) and app 7 of the [Vibe Build Series](https://github.com/saad-official/vibe-build-series).

## Why

Commit messages hold the facts, not the story. Writing notes by hand gets skipped; template tools produce lists nobody reads. The interesting engineering is not the prompt: it is chunking inputs that do not fit a context window, routing cheap and capable models to the right step, refusing to let the model invent a PR number, and measuring all of it with a golden set.

## How it works

```
collect -> normalise -> chunk -> map (gpt-oss-20b) -> verify refs -> reduce (gpt-oss-120b) -> verify -> render
GitHub     PR-folded    ~4.5k    category, summaries,   drop refs not   intro, order, dedupe    breaking   Markdown
REST       ChangeItems  tokens   breaking + confidence  in the range    (never rewrites items)  >= 0.6     + JSON
```

- **Two documents, one set of facts.** Both are rendered from the same verified item list; the reducer only writes intros, orders items and proposes duplicates.
- **Nothing cited that is not in the range.** Every PR number and SHA the model emits is checked in code; unknown ones are dropped and reported, skipped inputs get a plain fallback item.
- **Resumable.** Each stage is checkpointed in Postgres, so a serverless request that hits its time limit resumes instead of restarting.
- **Measured.** A 10-repo golden set with code-based scorers runs in CI against recorded model outputs; the live suite and an LLM judge run on demand.

Details: [architecture](docs/architecture.md) · [model routing](docs/decisions/0001-model-routing.md) · [hosting](docs/decisions/0002-hosting.md) · [verification](docs/decisions/0003-verification-over-trust.md) · [llm-kit dependency](docs/decisions/0004-llm-kit-dependency.md) · [evals](docs/evals.md) · [costs](docs/costs.md)

## Quick start

```bash
uv tool install git+https://github.com/saad-official/changelog-forge

export GROQ_API_KEY=...        # map and reduce tiers
export GEMINI_API_KEY=...      # fallback tier (optional)
export GITHUB_TOKEN=...        # optional: 5,000 GitHub requests/hour instead of 60

changelog-forge honojs/hono v4.13.10..v4.13.13 --audience user,dev
changelog-forge https://github.com/honojs/hono/compare/v4.13.10...v4.13.13
changelog-forge honojs/hono v4.13.10..v4.13.13 --json --out notes.json
```

Progress and the cost ledger go to stderr, the notes to stdout or `--out`.

## API

```bash
uv run uvicorn changelog_forge.api.main:app --port 7860     # OpenAPI at /api/docs
```

`POST /api/runs` → `POST /api/runs/{id}/process` → `GET /api/runs/{id}/events` (SSE) → `GET /api/runs/{id}` / `GET /api/runs/{id}.md?audience=dev`. Contract, error codes and event shapes: [docs/api.md](docs/api.md). Deploys to Vercel's Python runtime from the repository root (`main.py`, `vercel.json`) or anywhere as a Docker image ([setup](docs/setup.md)).

## GitHub Action

```yaml
# .github/workflows/release-notes.yml
name: Release notes
on:
  push:
    tags: ["v*"]

permissions:
  contents: write        # update the release body
  pull-requests: write   # or comment on a release PR

jobs:
  notes:
    runs-on: ubuntu-latest
    steps:
      - uses: saad-official/changelog-forge@v1
        with:
          audiences: user,dev
          output: release-body       # or: pr-comment
          github-token: ${{ secrets.GITHUB_TOKEN }}
          groq-api-key: ${{ secrets.GROQ_API_KEY }}
```

On a tag push the range is the previous tag of the same prefix to the pushed tag; on a `pull_request` event it is the PR's base to head; `base:`/`head:` inputs override both. `output: release-body` creates or updates the release for the tag (user notes, developer notes folded underneath); `pr-comment` comments on the pull request. Optional input: `gemini-api-key`. The action runs this repository's Docker image ([action.yml](action.yml), [entrypoint](action/entrypoint.sh)).

## Development

```bash
uv sync
uv run ruff check . && uv run ruff format --check . && uv run pytest -q
uv run evals                          # golden set, recorded model outputs, no network
uv run evals --live --record --judge  # real models; re-records cassettes, writes docs/evals.md
uv run python scripts/smoke_live.py   # one real run, prints the ledger
```

No test touches the network: GitHub is mocked with `respx`, models with a fake that records into a real llm-kit `Ledger`, Postgres with an in-memory store. Setup, environment variables and deploys: [docs/setup.md](docs/setup.md).

## Stack

Python 3.12 · FastAPI · Pydantic · [llm-kit](https://github.com/saad-official/ai-engineering-journey/tree/main/packages/llm-kit) (thin provider layer with cost ledger) · Groq (`gpt-oss-20b`, `gpt-oss-120b`) and Gemini (`gemini-3.5-flash-lite`) free tiers · Neon Postgres (psycopg 3) · tiktoken · Typer · Next.js 16 UI (`web/`) · GitHub Action · pytest + respx · Vercel (API and web), Docker for anywhere else

## Learning: explain it back

Questions to answer without looking, with model answers.

**1. Why route map and reduce to different models instead of using the best model for everything?**
The two steps have different shapes. Map is many small, structured, low-stakes calls (classify one change, one sentence each), and its mistakes are bounded: the verifier removes bad references and one weak summary affects one bullet. Reduce is two calls whose output (the intro, the ordering) is the first thing a reader sees. Paying the capable model's rate on every map call buys little; using the cheap model for the prose is what users notice. The routing table makes the trade explicit and measurable: the eval suite reports quality and cost per 100 commits for any routing change, and the first live run showed why it matters (a fallback to a model with 8x pricier output tokens put the run 4x over the cost target).

**2. Why verify references in code instead of telling the model not to invent them?**
Because the set of valid references is known exactly, and checking membership in a set is free, deterministic and testable, while a prompt is a request the model can ignore. Models invent plausible PR numbers, cite PRs mentioned inside a body that are not in the range (the pydantic backports case), and reformat references (`5479` for `#5479`). The verifier drops anything not in the collected set, canonicalises what is, records every change it made, and gives skipped inputs a fallback item. A second "check your references" model call would cost a full request and could be wrong in the same way. Use models for judgement, code for facts.

**3. Why cache GitHub data by `(repo, sha)`?**
A commit is immutable: its message, author and the PR it was merged through do not change, so once looked up it never needs to be fetched again. Ranges overlap constantly (`v1.2..v1.3`, then `v1.2..v1.4`, the same range re-run after a prompt change), and the PR lookup is one API call per commit against a budget of 60 per hour without a token. With the cache, a re-run only pays for new commits. Compare and repository calls are not keyed by SHA (refs move), so they use ETags instead: a `304 Not Modified` does not count against an authenticated client's rate limit.

**4. Why does the ledger report cost at paid rates when every call runs on a free tier?**
"Free tier" is a quota, not a price. The number that decides whether a feature can ship is cost per user action at the rate you would pay with real traffic, and measuring it from the first run costs nothing. It also makes regressions visible: a prompt that quietly doubled its tokens, or a fallback silently serving most calls, shows up in dollars before it shows up anywhere else. The ledger is also a control, not just a receipt: its $0.05 ceiling is checked before each call, so a run cannot loop into a bill.
