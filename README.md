# Changelog Forge

**A git range in, release notes for two audiences out.** Point Changelog Forge at a public GitHub repository and a range (`v1.2.0..v1.3.0`). It collects the commits and pull requests, groups them into token-sized batches, has a cheap model classify and summarise each batch into a strict schema, has a better model merge them into prose for end users and for developers, verifies every commit and PR reference against the input, and renders Markdown and JSON. Every run reports its token usage and cost at paid rates.

Level 1 project of the [AI Engineering Journey](https://github.com/saad-official/ai-engineering-journey) and app 7 of the [Vibe Build Series](https://github.com/saad-official/vibe-build-series).

## Why

Commit messages hold the facts, not the story. Writing notes by hand gets skipped; template tools produce lists nobody reads. The interesting engineering is not the prompt: it is chunking inputs that do not fit a context window, routing cheap and capable models to the right step, refusing to let the model invent a PR number, and measuring all of it with a golden set.

## Stack

Python 3.12 · FastAPI · Pydantic · [llm-kit](https://github.com/saad-official/ai-engineering-journey/tree/main/packages/llm-kit) (thin provider layer with cost ledger) · Groq and Gemini free tiers · Neon Postgres · Next.js 16 UI · GitHub Action · Vitest/pytest · Hugging Face Spaces or Render + Vercel

## Docs

- [Spec](docs/spec.md)
