# Changelog Forge: web

Next.js 16 (App Router) front end for the Changelog Forge API. Deployed to Vercel with this folder as the project root.

## Run locally

```bash
pnpm install
cp .env.example .env.local        # NEXT_PUBLIC_API_URL defaults to http://localhost:7860
pnpm dev
```

Without the API, run on fixtures: set `NEXT_PUBLIC_API_MOCK=1` (in `.env.local` or the shell) and restart `pnpm dev`.
Mock mode serves a real range (honojs/hono v4.5.11..v4.6.0) from `lib/mock.ts`. On `/forge`, a repo name containing
`rate-limit`, `missing`, `huge`, `fail` or `offline` shows the 429, 404, commit-cap, failed-run and retry-processing
states; `/runs/demo-done` opens a finished run.

## Checks

```bash
pnpm exec next typegen && pnpm exec tsc --noEmit && pnpm lint && pnpm test
NEXT_PUBLIC_API_URL=http://localhost:7860 pnpm build
```

## Layout

- `app/` pages: `/` landing, `/forge` form, `/runs/[id]` live run, `/docs`, `api/health` (proxies the API health check).
- `lib/api.ts` the API contract (zod, tolerant of missing fields), `lib/mock.ts` fixtures, `lib/notes.ts` ReleaseNotes
  normalisation and Markdown, `lib/progress.ts` event stream to stage track, `lib/snippets.ts` CLI/API/Action snippets.
- `components/notes/` documents, chips, verification and usage panels (server-safe, shared by landing and run page).
- `components/run/` the live run: `use-run.ts` (GET, POST /process, SSE with polling fallback), terminal log, stage track.
