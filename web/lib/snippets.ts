/**
 * CLI, API and GitHub Action snippets shown on the landing page and /docs.
 * Single source for the web app: keep these in step with the repo README.
 */

export const REPO_URL = "https://github.com/saad-official/changelog-forge";
export const JOURNEY_URL = "https://github.com/saad-official/ai-engineering-journey";
export const SERIES_URL = "https://github.com/saad-official/vibe-build-series";

export const cliInstall = `uv tool install git+${REPO_URL}`;

export const cliUsage = `changelog-forge honojs/hono v4.5.11..v4.6.0 --audience user,dev`;

export const cliExamples = `# Markdown for both audiences on stdout
changelog-forge honojs/hono v4.5.11..v4.6.0 --audience user,dev

# A compare URL works too
changelog-forge https://github.com/honojs/hono/compare/v4.5.11...v4.6.0

# JSON (the ReleaseNotes model) written to a file
changelog-forge honojs/hono v4.5.11..v4.6.0 --json --out notes.json`;

export const cliEnv = `export GROQ_API_KEY=...        # map and reduce tiers
export GEMINI_API_KEY=...      # fallback tier (optional)
export GITHUB_TOKEN=...        # optional: 5,000 GitHub requests/hour instead of 60`;

export function curlCreate(api: string) {
  return `curl -s -X POST ${api}/api/runs \\
  -H 'Content-Type: application/json' \\
  -d '{"repo":"honojs/hono","base":"v4.5.11","head":"v4.6.0","audiences":["user","dev"]}'
# -> 202 {"id":"<run id>","status":"queued"}`;
}

export function curlProcess(api: string) {
  return `# Run the pipeline (holds the request open until the run finishes, up to ~250 s)
curl -s -X POST ${api}/api/runs/<run id>/process`;
}

export function curlEvents(api: string) {
  return `# Progress as Server-Sent Events: replays history, then tails until done|failed
curl -N ${api}/api/runs/<run id>/events`;
}

export function curlResult(api: string) {
  return `# The finished run: status, usage, outputs, verification
curl -s ${api}/api/runs/<run id>

# Markdown for one audience
curl -s "${api}/api/runs/<run id>.md?audience=dev" -o CHANGELOG-dev.md`;
}

export const actionWorkflow = `# .github/workflows/release-notes.yml
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
          github-token: \${{ secrets.GITHUB_TOKEN }}
          groq-api-key: \${{ secrets.GROQ_API_KEY }}`;
