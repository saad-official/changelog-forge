# 0004 — Depending on llm-kit: a pinned git reference, with a dev-time path overlay

Date: 2026-10-04. Status: accepted.

## Context

[llm-kit](https://github.com/saad-official/ai-engineering-journey/tree/main/packages/llm-kit)
is the journey's own provider layer (retries, budgets, structured output, cost ledger). It
lives in the journey monorepo; Changelog Forge is its own repository. The dependency has to
work for:

1. Vercel, which installs from `pyproject.toml` / `uv.lock` in this repository alone;
2. `docker build` from this repository alone (the Render fallback, and the GitHub Action);
3. `uv tool install git+https://github.com/saad-official/changelog-forge` (the CLI install
   the web app prints), on any OS;
4. CI on ubuntu;
5. local development next to the llm-kit source, where a fix to llm-kit should be testable
   here without publishing anything.

## Options

1. **Path source in `[tool.uv.sources]`** (`../../packages/llm-kit`). Perfect for 5, fails
   1-4: the path does not exist outside the monorepo.
2. **Two sources gated by a platform marker** (path on `win32`, git elsewhere). Tried and
   it locks fine, but `uv tool install git+...` on a Windows machine would try the path and
   fail, and "Windows = dev box" is a coincidence, not a rule.
3. **PEP 508 git reference pinned to a commit in `project.dependencies`**, no uv source
   override, plus a per-command editable overlay for local development. Works for 1-4 with
   every installer (uv honours it, pip honours it, the wheel metadata carries it).
4. Publish llm-kit to PyPI. Cleanest for consumers, but a release process for a learning
   library that changes weekly; premature.

## Decision

Option 3.

```toml
dependencies = [
  "llm-kit @ git+https://github.com/saad-official/ai-engineering-journey.git@2d83dd543611d3644106d29f2f12ee8b092d9d09#subdirectory=packages/llm-kit",
  ...
]
[tool.hatch.metadata]
allow-direct-references = true   # hatchling refuses direct references without it
```

`uv.lock` records the same commit, so `uv sync --frozen` (Docker, CI, Vercel) is
reproducible. The Dockerfile installs `git` in the build stage because uv clones git
dependencies with it.

**Dev-time override** (verified): uv's `--with-editable` layers the local checkout over the
project environment for one command, without touching `pyproject.toml` or `uv.lock`:

```powershell
uv run --with-editable ../../packages/llm-kit pytest -q
uv run --with-editable ../../packages/llm-kit python scripts/smoke_live.py
```

`python -c "import llm_kit; print(llm_kit.__file__)"` under that command prints the
monorepo path; without it, the site-packages copy of the pinned commit.

**Bumping llm-kit**: push the llm-kit change to the journey repo, replace the commit hash in
`pyproject.toml`, run `uv lock`, run the tests and `uv run evals` (routing or retry changes
in llm-kit can move eval numbers).

## Consequences

- Every environment runs the same llm-kit unless a developer explicitly overlays it, and CI
  always tests the pinned commit. A local overlay that diverges is caught when the pin is
  bumped.
- The journey repo must stay public (it is) or every install needs credentials.
- What llm-kit lacked for this project, kept as a thin adapter here (`llm.py`,
  `observability.py`) rather than edited upstream: cross-provider fallback, tokens-per-
  minute pacing, a same-route resample when Groq rejects output against the strict schema
  (llm-kit classifies that 400 as permanent), a tracing hook (the Langfuse export reads
  Ledger records after the run), async support (the pipeline runs in a worker thread), and
  a way to inject `Settings` from a project's own `.env` (we pass every field explicitly).
