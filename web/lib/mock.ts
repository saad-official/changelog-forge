/**
 * Mock mode (`NEXT_PUBLIC_API_MOCK=1`): fixture responses shaped exactly like
 * the API's, so the UI can be built and screenshotted without the backend.
 *
 * The fixture is a real range, honojs/hono v4.5.11..v4.6.0 (17 commits). Every
 * SHA and PR number below exists in that range; the prose is a hand-written
 * sample of what the pipeline produces, and the dropped `#3390` is a planted
 * "invented" reference to show the verifier at work.
 *
 * Magic inputs on /forge (mock mode only):
 *   repo containing "rate-limit" -> 429      "missing"  -> 404 repo not found
 *   "huge"                      -> commit cap "fail"     -> run that fails in map
 *   "offline"                   -> first /process call fails with a network error
 * Run id `demo-done` opens an already finished run (for screenshots).
 */
import { ApiError, networkError, parseApiError } from "./errors";
import { normaliseNotes, notesToMarkdown } from "./notes";
import type { CreateRunInput, CreatedRun, ProcessOutcome, RunEvent, RunEventHandlers } from "./api";

export const EXAMPLE_REPO = "honojs/hono";
export const EXAMPLE_BASE = "v4.5.11";
export const EXAMPLE_HEAD = "v4.6.0";

const GH = `https://github.com/${EXAMPLE_REPO}`;
const pr = (n: number) => ({ kind: "pr", id: String(n), url: `${GH}/pull/${n}` });
const sha = (s: string) => ({ kind: "commit", id: s, url: `${GH}/commit/${s}` });

const C = {
  docsTypo: "a1b477ccf7704de4a7d7824a28da917149392c7b",
  denoJsr: "f9a23a9992979fed79b0703ab8b3a3ce49f7175f",
  permissionsPolicy: "5a25e33e93aa8d4d68d8fb7e1c8e866a06a9710b",
  cfPages: "8e56989cde700682aaf6b383ca8b821220e8309d",
  wsGenerics: "6f69bf04b744d88efa608dd4458dd650ad57cdf0",
  jsxEncoding: "39600c4449ad0835014730f577c6ebb2721e1a4c",
  contextStorage: "fdf77862acbbfc1540ff0732a4cfd74a55781393",
  precompressed: "c8d5e3461dd08d694e4175170ac60326911210f7",
  streamSse: "8ca155ec9b7780d9bb685b2d90881706d315fd61",
  mutableHeaders: "c2b0de42a0fbe54c9862ed505c4b9ee46ed435ac",
  policyPerf: "3c4d4c2b59dc83a513d7fbceef4fca23f0774397",
  onFound: "a86f3cea5f3cc028a881863ac4ec1d2281d2441d",
  basicAuthMsg: "c50be25c9ef6d770a077ead0ec7f0b5224237d86",
  bearerAuthMsg: "c240ea559017f1aff522abec2845c58c87c43de7",
  bearerTypo: "743f66c13acc7c93f09fdd5b43a2017a6e52454c",
} as const;

export const exampleUserNotes = {
  audience: "user",
  title: "What's new in Hono 4.6.0",
  intro:
    "Hono 4.6.0 adds a way to reach the current request from anywhere in your code, serves pre-compressed static files, and lets the auth middlewares answer with your own message. Nothing you rely on should change.",
  sections: [
    {
      category: "features",
      items: [
        { summary: "New Context Storage middleware: read the current request context from any function, without passing it around.", refs: [pr(3373), sha(C.contextStorage)] },
        { summary: "Static files can be served pre-compressed when a compressed copy sits next to the original.", refs: [pr(3366), sha(C.precompressed)] },
        { summary: "Serve Static can run your code for every file it serves, for example to set cache headers.", refs: [pr(3396), sha(C.onFound)] },
        { summary: "Basic and Bearer auth can reply with your own message when a request is rejected.", refs: [pr(3371), pr(3372)] },
        { summary: "Secure Headers can now set a Permissions-Policy header.", refs: [pr(3314), sha(C.permissionsPolicy)] },
        { summary: "Server-sent event streams accept promises and async JSX.", refs: [pr(3344), sha(C.streamSse)] },
      ],
    },
    { category: "fixes", items: [{ summary: "Corrected a typo in Bearer auth.", refs: [pr(3404), sha(C.bearerTypo)] }] },
    { category: "performance", items: [{ summary: "Permissions-Policy headers are built faster.", refs: [pr(3398), sha(C.policyPerf)] }] },
  ],
};

export const exampleDevNotes = {
  audience: "dev",
  title: "hono v4.5.11..v4.6.0",
  intro:
    "Minor release: 10 features, 1 fix, 1 performance change, no confirmed breaking changes. One change to Response header mutability is flagged as possibly breaking; read it if you wrap fetch() responses.",
  sections: [
    {
      category: "features",
      items: [
        { summary: "`contextStorage()` middleware with `getContext()` exposes the current `Context` through AsyncLocalStorage.", refs: [pr(3373), sha(C.contextStorage)] },
        { summary: "`serveStatic({ precompressed: true })` serves a pre-compressed sibling file based on `Accept-Encoding`.", refs: [pr(3366), sha(C.precompressed)] },
        { summary: "`serveStatic({ onFound })` callback runs for each file served.", refs: [pr(3396), sha(C.onFound)] },
        { summary: "`basicAuth` and `bearerAuth` take options for a custom response message on failure.", refs: [pr(3371), pr(3372), sha(C.basicAuthMsg), sha(C.bearerAuthMsg)] },
        { summary: "`secureHeaders` can set `Permissions-Policy`.", refs: [pr(3314), sha(C.permissionsPolicy)] },
        { summary: "`streamSSE`: `data` may be a `Promise<string>` or an (async) JSX element.", refs: [pr(3344), sha(C.streamSse)] },
        { summary: "`WSContext` takes a generic type parameter.", refs: [pr(3337), sha(C.wsGenerics)] },
        { summary: "Cloudflare Pages `handleMiddleware` exposes `c.env.eventContext`.", refs: [pr(3332), sha(C.cfPages)] },
        { summary: "`jsxRenderer` sets `Content-Encoding` when `stream: true`.", refs: [pr(3355), sha(C.jsxEncoding)] },
        {
          summary: "Headers of a `Response` returned by `fetch()` are now mutable on `c.res`.",
          possibly_breaking: true,
          breaking_confidence: 0.45,
          migration_note: "Only relevant if you relied on those headers being immutable; middleware that set headers after `await next()` now succeeds where it threw before.",
          refs: [pr(3318), sha(C.mutableHeaders)],
        },
      ],
    },
    { category: "fixes", items: [{ summary: "`bearerAuth`: typo fix.", refs: [pr(3404), sha(C.bearerTypo)] }] },
    { category: "performance", items: [{ summary: "`getPermissionsPolicyDirectives` optimised.", refs: [pr(3398), sha(C.policyPerf)] }] },
    { category: "docs", items: [{ summary: "JSDoc typo in `jsx-renderer`.", refs: [pr(3378), sha(C.docsTypo)] }] },
    { category: "internal", items: [{ summary: "Deno tests use the latest JSR libraries.", refs: [pr(3375), sha(C.denoJsr)] }] },
  ],
};

const userMarkdown = notesToMarkdown(normaliseNotes(exampleUserNotes, EXAMPLE_REPO)!);
const devMarkdown = notesToMarkdown(normaliseNotes(exampleDevNotes, EXAMPLE_REPO)!);

/** Usage at Groq's paid rates for the two models (per 1M tokens: 20b $0.075 in / $0.30 out; 120b $0.15 / $0.60). */
const exampleUsage = {
  prompt_tokens: 15358,
  completion_tokens: 4516,
  usd: 0.003713,
  max_usd: 0.05,
  by_model: [
    { model: "openai/gpt-oss-20b", provider: "groq", stage: "map", calls: 2, prompt_tokens: 9146, completion_tokens: 2050, usd: 0.001301 },
    { model: "openai/gpt-oss-120b", provider: "groq", stage: "reduce", calls: 2, prompt_tokens: 6212, completion_tokens: 2466, usd: 0.002412 },
  ],
};

/** The finished run, exactly as `GET /api/runs/{id}` returns it. */
export const exampleRun = {
  id: "demo-hono",
  status: "done",
  repo: EXAMPLE_REPO,
  base: EXAMPLE_BASE,
  head: EXAMPLE_HEAD,
  audiences: ["user", "dev"],
  commit_count: 17,
  group_count: 2,
  usage: exampleUsage,
  outputs: {
    user: { markdown: userMarkdown, json: exampleUserNotes },
    dev: { markdown: devMarkdown, json: exampleDevNotes },
  },
  verified: {
    checked_refs: 41,
    dropped_refs: ["#3390"],
    downgraded: [
      {
        summary: "Headers of a Response returned by fetch() are now mutable on c.res.",
        refs: ["#3318"],
        breaking_confidence: 0.45,
        reason: "confidence 0.45 is below 0.60: shown as possibly breaking in the dev notes, left out of the user notes",
      },
    ],
  },
  error: null,
  created_at: "2026-10-04T09:12:03Z",
  finished_at: "2026-10-04T09:12:12Z",
};

type TimedEvent = Omit<RunEvent, "at"> & { offset: number };

const ev = (offset: number, seq: number, kind: string, message: string, data: Record<string, unknown> = {}): TimedEvent => ({
  offset,
  seq,
  kind,
  message,
  data,
});

export const exampleEvents: TimedEvent[] = [
  ev(0, 1, "status", "run queued", { status: "queued" }),
  ev(500, 2, "collect", "collecting honojs/hono v4.5.11...v4.6.0", { status: "collecting" }),
  ev(1500, 3, "collect", "collected 17 commits, 16 pull requests (cache: 0 hits, 17 fetched)", { commit_count: 17, pr_count: 16, cache_hits: 0 }),
  ev(1900, 4, "group", "normalised 17 commits into 15 change items (1 merge, 1 version bump folded)", { item_count: 15 }),
  ev(2300, 5, "group", "chunked into 2 groups: 5,112 + 3,804 tokens (o200k_base estimate)", { group_count: 2, status: "mapping" }),
  ev(2700, 6, "map", "drafting group 1 of 2 with openai/gpt-oss-20b", { group: 1, groups: 2, model: "openai/gpt-oss-20b" }),
  ev(3900, 7, "map", "group 1 of 2: 9 items, 5,342 in / 1,104 out", { group: 1, groups: 2, items: 9 }),
  ev(4100, 8, "map", "drafting group 2 of 2 with openai/gpt-oss-20b", { group: 2, groups: 2, model: "openai/gpt-oss-20b" }),
  ev(5100, 9, "map", "group 2 of 2: 6 items, 3,804 in / 946 out", { group: 2, groups: 2, items: 6 }),
  ev(5400, 10, "reduce", "merging 15 items, 2 duplicates folded", { status: "reducing", items: 13 }),
  ev(6000, 11, "reduce", "writing user notes with openai/gpt-oss-120b", { audience: "user", model: "openai/gpt-oss-120b" }),
  ev(6900, 12, "reduce", "writing dev notes with openai/gpt-oss-120b", { audience: "dev", model: "openai/gpt-oss-120b" }),
  ev(7700, 13, "verify", "verifying 41 references against 17 commits and 16 pull requests", { status: "verifying", refs: 41 }),
  ev(7950, 14, "verify", "dropped #3390: not in the collected range", { level: "warn", ref: "#3390" }),
  ev(8150, 15, "verify", "downgraded #3318 to possibly breaking (confidence 0.45 < 0.60)", { level: "warn", ref: "#3318", confidence: 0.45 }),
  ev(8400, 16, "render", "rendered user.md, dev.md and release-notes.json", {}),
  ev(8600, 17, "done", "done in 8.6 s: 19,874 tokens, $0.0037 at paid rates", { status: "done" }),
];

const failedEvents: TimedEvent[] = [
  ev(0, 1, "status", "run queued", { status: "queued" }),
  ev(500, 2, "collect", "collecting honojs/hono v4.5.11...v4.6.0", { status: "collecting" }),
  ev(1400, 3, "collect", "collected 17 commits, 16 pull requests (cache: 17 hits)", { commit_count: 17 }),
  ev(1800, 4, "group", "chunked into 2 groups: 5,112 + 3,804 tokens", { group_count: 2, status: "mapping" }),
  ev(2200, 5, "map", "drafting group 1 of 2 with openai/gpt-oss-20b", { group: 1, groups: 2 }),
  ev(3300, 6, "map", "groq returned 503; retrying (1 of 2)", { level: "warn" }),
  ev(4200, 7, "map", "fallback gemini-3.5-flash-lite returned 429 rate limited", { level: "warn" }),
  ev(4500, 8, "failed", "map failed for group 1 of 2: every provider in the route refused", { status: "failed" }),
];

const failedRun = {
  ...exampleRun,
  id: "demo-failed",
  status: "failed",
  group_count: 2,
  finished_at: "2026-10-04T09:12:07Z",
  usage: { prompt_tokens: 5342, completion_tokens: 0, usd: 0.0004, by_model: [{ model: "openai/gpt-oss-20b", stage: "map", calls: 1, prompt_tokens: 5342, completion_tokens: 0, usd: 0.0004 }] },
  outputs: {},
  verified: { dropped_refs: [], downgraded: [] },
  error: "Map step failed for group 1 of 2: groq returned 503 twice and the fallback (gemini-3.5-flash-lite) was rate limited. Nothing was published. Try again in a minute.",
};

/* ------------------------------------------------------------------ */
/* Mock server state (per tab)                                          */

const clock = new Map<string, number>();
const processAttempts = new Map<string, number>();

function fixtureFor(id: string) {
  if (id.startsWith("demo-failed")) return { run: failedRun, events: failedEvents };
  if (id.startsWith("demo-")) return { run: exampleRun, events: exampleEvents };
  return null;
}

function elapsed(id: string): number {
  // demo-done is already finished: handy for screenshots of the final state.
  if (id.startsWith("demo-done")) return Number.MAX_SAFE_INTEGER;
  const start = clock.get(id);
  return start === undefined ? -1 : Date.now() - start;
}

function dueEvents(events: TimedEvent[], id: string): TimedEvent[] {
  const t = elapsed(id);
  // The "queued" event exists from creation; everything else waits for /process.
  return events.filter((e) => e.offset === 0 || (t >= 0 && e.offset <= t));
}

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export async function mockCreateRun(body: CreateRunInput): Promise<CreatedRun> {
  await delay(450);
  const repo = body.repo.toLowerCase();
  if (repo.includes("rate-limit")) {
    throw parseApiError(429, { detail: { code: "rate_limited", message: "10 runs per hour per address. Try again in 41 minutes.", retry_after: 2460 } });
  }
  if (repo.includes("missing")) {
    throw parseApiError(404, { detail: { code: "repo_not_found", message: `${body.repo} was not found, or it is private and no token was given.` } });
  }
  if (repo.includes("huge")) {
    throw parseApiError(422, {
      detail: { code: "commit_cap", message: `${body.base}..${body.head} has 1,284 commits; one run takes up to 400. Pick a narrower range.`, limit: 400, commit_count: 1284 },
    });
  }
  const id = repo.includes("fail") ? "demo-failed" : repo.includes("offline") ? "demo-offline" : "demo-hono";
  clock.delete(id);
  processAttempts.delete(id);
  return { id, status: "queued" };
}

export function mockGetRun(id: string): unknown {
  const fx = fixtureFor(id);
  if (!fx) throw new ApiError({ status: 404, code: "run_not_found", message: "No run with that id. In mock mode, run ids start with demo-." });
  const due = dueEvents(fx.events, id);
  const last = [...due].reverse().find((e) => typeof e.data.status === "string");
  const status = (last?.data.status as string | undefined) ?? "queued";
  if (status === fx.run.status) return { ...fx.run, id };
  const counts = Object.assign({}, ...due.map((e) => e.data)) as Record<string, unknown>;
  return {
    ...fx.run,
    id,
    status,
    commit_count: counts.commit_count ?? 0,
    group_count: counts.group_count ?? 0,
    usage: { prompt_tokens: 0, completion_tokens: 0, usd: 0, by_model: [] },
    outputs: {},
    verified: null,
    error: null,
    finished_at: null,
  };
}

export function mockSubscribe(id: string, handlers: RunEventHandlers): () => void {
  const fx = fixtureFor(id);
  if (!fx) {
    setTimeout(() => handlers.onError(true), 0);
    return () => {};
  }
  let sent = 0;
  const base = Date.now();
  const tick = () => {
    for (const e of dueEvents(fx.events, id)) {
      if (e.seq <= sent) continue;
      sent = e.seq;
      const { offset, ...rest } = e;
      handlers.onEvent({ ...rest, at: new Date((clock.get(id) ?? base) + offset).toISOString() });
      if (e.kind === "done" || e.kind === "failed") {
        clearInterval(timer);
        return;
      }
    }
  };
  const timer = setInterval(tick, 120);
  setTimeout(() => {
    handlers.onOpen?.();
    tick();
  }, 0);
  return () => clearInterval(timer);
}

export async function mockProcess(id: string): Promise<ProcessOutcome> {
  const fx = fixtureFor(id);
  if (!fx) throw new ApiError({ status: 404, code: "run_not_found", message: "No run with that id." });
  const attempts = (processAttempts.get(id) ?? 0) + 1;
  processAttempts.set(id, attempts);
  if (id.startsWith("demo-offline") && attempts === 1) {
    await delay(700);
    throw networkError("the mock API");
  }
  if (clock.has(id) || id.startsWith("demo-done")) return { outcome: "claimed" };
  clock.set(id, Date.now());
  const total = fx.events[fx.events.length - 1].offset;
  await delay(total);
  return { outcome: "processed", status: fx.run.status as "done" | "failed" };
}

export function mockHealth() {
  return { ok: true, version: "mock", providers: { groq: true, gemini: true }, db: true };
}
