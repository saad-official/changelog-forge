import { z } from "zod";
import { API_MOCK, API_URL } from "./config";
import { ApiError, networkError, parseApiError } from "./errors";
import * as mock from "./mock";

/*
  Contract with the FastAPI service (spec §6). Parsing is deliberately
  tolerant: optional fields may be missing or null, numbers may be absent
  while a run is in progress, and unknown extra fields are ignored. A run
  that parses at all renders; the UI never crashes on a partial payload.
*/

export const RUN_STATUSES = ["queued", "collecting", "mapping", "reducing", "verifying", "done", "failed"] as const;
export type RunStatus = (typeof RUN_STATUSES)[number];
export const AUDIENCES = ["user", "dev"] as const;
export type Audience = (typeof AUDIENCES)[number];

export function isTerminal(status: string | undefined): status is "done" | "failed" {
  return status === "done" || status === "failed";
}

const count = z.number().nonnegative().nullish().catch(null).transform((v) => v ?? 0);
const optText = z.string().nullish().catch(null).transform((v) => v ?? undefined);

const status = z
  .string()
  .catch("queued")
  .transform((s): RunStatus => ((RUN_STATUSES as readonly string[]).includes(s) ? (s as RunStatus) : "queued"));

export const ModelUsageSchema = z.object({
  model: z.string().catch("unknown"),
  provider: optText,
  stage: optText,
  calls: z.number().nullish().catch(null).transform((v) => v ?? undefined),
  prompt_tokens: count,
  completion_tokens: count,
  usd: count,
});
export type ModelUsage = z.infer<typeof ModelUsageSchema>;

/** by_model may arrive as a list or as `{ "<model>": { ... } }`. */
const byModel = z
  .union([
    z.array(z.unknown()),
    z.record(z.string(), z.unknown()),
  ])
  .nullish()
  .catch(null)
  .transform((raw): ModelUsage[] => {
    if (!raw) return [];
    const entries = Array.isArray(raw)
      ? raw
      : Object.entries(raw).map(([model, v]) => (typeof v === "object" && v !== null ? { model, ...v } : { model }));
    return entries.flatMap((e) => {
      const r = ModelUsageSchema.safeParse(e);
      return r.success ? [r.data] : [];
    });
  });

export const UsageSchema = z
  .object({
    prompt_tokens: count,
    completion_tokens: count,
    total_tokens: z.number().nullish().catch(null),
    usd: count,
    max_usd: z.number().nullish().catch(null).transform((v) => v ?? undefined),
    by_model: byModel,
  })
  .transform((u) => ({
    ...u,
    total_tokens: u.total_tokens ?? u.prompt_tokens + u.completion_tokens,
  }));
export type Usage = z.infer<typeof UsageSchema>;

export const EMPTY_USAGE: Usage = { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, usd: 0, max_usd: undefined, by_model: [] };

export const DowngradedSchema = z
  .object({
    summary: optText,
    title: optText,
    text: optText,
    refs: z.array(z.unknown()).nullish().catch(null),
    ref: z.unknown().optional(),
    breaking_confidence: z.number().nullish().catch(null),
    confidence: z.number().nullish().catch(null),
    reason: optText,
  })
  .transform((d) => ({
    summary: d.summary ?? d.title ?? d.text ?? "Unnamed item",
    refs: d.refs ?? (d.ref !== undefined ? [d.ref] : []),
    confidence: d.breaking_confidence ?? d.confidence ?? undefined,
    reason: d.reason,
  }));
export type Downgraded = z.infer<typeof DowngradedSchema>;

const downgradedList = z
  .array(z.unknown())
  .nullish()
  .catch(null)
  .transform((list): Downgraded[] =>
    (list ?? []).flatMap((d) => {
      if (typeof d === "string") return [{ summary: d, refs: [], confidence: undefined, reason: undefined }];
      const r = DowngradedSchema.safeParse(d);
      return r.success ? [r.data] : [];
    }),
  );

const refList = z
  .array(z.unknown())
  .nullish()
  .catch(null)
  .transform((l) => (l ?? []).map((r) => (typeof r === "string" ? r : typeof r === "number" ? `#${r}` : JSON.stringify(r))));

export const VerifiedSchema = z.object({
  dropped_refs: refList,
  downgraded: downgradedList,
  checked_refs: z.number().nullish().catch(null).transform((v) => v ?? undefined),
});
export type Verified = z.infer<typeof VerifiedSchema>;

export const OutputSchema = z.object({
  markdown: z.string().nullish().catch(null).transform((v) => v ?? ""),
  json: z.unknown().optional(),
  verified: VerifiedSchema.nullish().catch(null),
});
export type AudienceOutput = z.infer<typeof OutputSchema>;

const optOutput = OutputSchema.nullish().catch(null).transform((v) => v ?? undefined);

export const RunDetailSchema = z
  .object({
    id: z.union([z.string(), z.number()]).transform(String),
    status,
    repo: z.string().catch(""),
    base: z.string().catch(""),
    head: z.string().catch(""),
    audiences: z.array(z.string()).nullish().catch(null),
    commit_count: count,
    group_count: count,
    usage: UsageSchema.nullish().catch(null).transform((u) => u ?? EMPTY_USAGE),
    outputs: z
      .object({ user: optOutput, dev: optOutput })
      .nullish()
      .catch(null)
      .transform((o) => o ?? { user: undefined, dev: undefined }),
    verified: VerifiedSchema.nullish().catch(null),
    error: optText,
    created_at: optText,
    finished_at: optText,
    prompt_versions: z.record(z.string(), z.unknown()).nullish().catch(null),
  })
  .transform((r) => {
    // Prefer the run-level verification; fall back to merging per-audience ones.
    const perAudience = [r.outputs.user?.verified, r.outputs.dev?.verified].filter((v): v is Verified => !!v);
    const verified: Verified = r.verified ?? {
      dropped_refs: [...new Set(perAudience.flatMap((v) => v.dropped_refs))],
      downgraded: perAudience.flatMap((v) => v.downgraded),
      checked_refs: undefined,
    };
    const audiences = (r.audiences ?? []).filter((a): a is Audience => a === "user" || a === "dev");
    return { ...r, audiences, verified };
  });
export type RunDetail = z.infer<typeof RunDetailSchema>;

export const CreatedRunSchema = z.object({
  id: z.union([z.string(), z.number()]).transform(String),
  status,
});
export type CreatedRun = z.infer<typeof CreatedRunSchema>;

export const RunEventSchema = z.object({
  seq: z.coerce.number().catch(0),
  at: z.string().nullish().catch(null).transform((v) => v ?? undefined),
  kind: z.string().catch("log"),
  message: z.string().nullish().catch(null).transform((v) => v ?? ""),
  data: z
    .record(z.string(), z.unknown())
    .nullish()
    .catch(null)
    .transform((d) => d ?? {}),
});
export type RunEvent = z.infer<typeof RunEventSchema>;

/** Parse one SSE `data:` payload. Returns null for keep-alives and junk. */
export function parseRunEvent(raw: string, fallbackSeq?: number): RunEvent | null {
  const text = raw.trim();
  if (text === "") return null;
  let json: unknown;
  try {
    json = JSON.parse(text);
  } catch {
    return null;
  }
  if (typeof json !== "object" || json === null || Array.isArray(json)) return null;
  const r = RunEventSchema.safeParse(json);
  if (!r.success) return null;
  if (r.data.seq === 0 && fallbackSeq !== undefined && !("seq" in json)) return { ...r.data, seq: fallbackSeq };
  return r.data;
}

/** The status an event implies, if any (from `data.status`, or the done/failed kinds). */
export function eventStatus(e: RunEvent): RunStatus | undefined {
  const s = e.data.status;
  if (typeof s === "string" && (RUN_STATUSES as readonly string[]).includes(s)) return s as RunStatus;
  if (e.kind === "done") return "done";
  if (e.kind === "failed") return "failed";
  return undefined;
}

export type CreateRunInput = {
  repo: string;
  base: string;
  head: string;
  audiences: Audience[];
  github_token?: string;
};

export const eventsUrl = (id: string) => `${API_URL}/api/runs/${encodeURIComponent(id)}/events`;
export const markdownUrl = (id: string, audience: Audience) =>
  `${API_URL}/api/runs/${encodeURIComponent(id)}.md?audience=${audience}`;

async function readBody(res: Response): Promise<unknown> {
  const text = await res.text();
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

async function request(path: string, init?: RequestInit): Promise<unknown> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { Accept: "application/json", ...(init?.body ? { "Content-Type": "application/json" } : {}), ...init?.headers },
      cache: "no-store",
    });
  } catch {
    throw networkError(API_URL);
  }
  const body = await readBody(res);
  if (!res.ok) throw parseApiError(res.status, body, res.headers.get("Retry-After"));
  return body;
}

function invalid(what: string): ApiError {
  return new ApiError({ status: 502, code: "server", message: `The API sent a ${what} this page could not read.` });
}

export async function createRun(input: CreateRunInput): Promise<CreatedRun> {
  const body: CreateRunInput = { repo: input.repo, base: input.base, head: input.head, audiences: input.audiences };
  if (input.github_token && input.github_token.trim() !== "") body.github_token = input.github_token.trim();
  if (API_MOCK) return mock.mockCreateRun(body);
  const parsed = CreatedRunSchema.safeParse(await request("/api/runs", { method: "POST", body: JSON.stringify(body) }));
  if (!parsed.success) throw invalid("run id");
  return parsed.data;
}

export async function getRun(id: string): Promise<RunDetail> {
  const raw = API_MOCK ? mock.mockGetRun(id) : await request(`/api/runs/${encodeURIComponent(id)}`);
  const parsed = RunDetailSchema.safeParse(raw);
  if (!parsed.success) throw invalid("run");
  return parsed.data;
}

export type RunEventHandlers = {
  onEvent: (event: RunEvent) => void;
  /** Connection-level failure (not an event of kind "failed"). */
  onError: (fatal: boolean) => void;
  onOpen?: () => void;
};

/** Named SSE event types we also listen for, in case the server sets `event:`. */
const NAMED_EVENTS = ["status", "collect", "group", "chunk", "map", "reduce", "verify", "render", "done", "failed", "log", "progress", "run_event"];

/**
 * Subscribe to a run's progress stream (replay, then tail until done|failed).
 * Returns an unsubscribe function. Uses EventSource, or the fixture stream in mock mode.
 */
export function subscribeToRun(id: string, handlers: RunEventHandlers): () => void {
  if (API_MOCK) return mock.mockSubscribe(id, handlers);
  if (typeof EventSource === "undefined") {
    handlers.onError(true);
    return () => {};
  }
  const source = new EventSource(eventsUrl(id));
  let fallbackSeq = 0;
  const onMessage = (ev: MessageEvent) => {
    fallbackSeq += 1;
    const lastId = Number(ev.lastEventId);
    const parsed = parseRunEvent(String(ev.data ?? ""), Number.isFinite(lastId) && lastId > 0 ? lastId : fallbackSeq);
    if (parsed) handlers.onEvent(parsed);
  };
  source.onopen = () => handlers.onOpen?.();
  source.onmessage = onMessage;
  for (const name of NAMED_EVENTS) source.addEventListener(name, onMessage as EventListener);
  source.onerror = (ev) => {
    // A server-sent `event: error` arrives here as a MessageEvent with data.
    if (ev instanceof MessageEvent && ev.data) {
      onMessage(ev);
      return;
    }
    handlers.onError(source.readyState === EventSource.CLOSED);
  };
  return () => source.close();
}

export type Health = {
  web: { ok: true };
  api: { reachable: boolean; url: string; status?: number; body?: unknown; error?: string; mock?: boolean };
};

export type ProcessOutcome = { outcome: "processed" | "claimed"; status?: RunStatus };

/**
 * Drive the pipeline. The API runs on a serverless runtime with no background
 * workers, so after `POST /api/runs` the client asks for processing explicitly:
 * `POST /api/runs/{id}/process` (no body) holds the request open while the run
 * executes (up to ~250 s) and returns `{ id, status }`. 409 means another request
 * already claimed the run, which is fine: progress still arrives over SSE.
 *
 * No body and no Content-Type keeps this a CORS "simple" request (no preflight),
 * and `keepalive` lets it outlive a navigation or a closed tab.
 */
export async function processRun(id: string): Promise<ProcessOutcome> {
  if (API_MOCK) return mock.mockProcess(id);
  let res: Response;
  try {
    res = await fetch(`${API_URL}/api/runs/${encodeURIComponent(id)}/process`, {
      method: "POST",
      keepalive: true,
      cache: "no-store",
    });
  } catch {
    throw networkError(API_URL);
  }
  const body = await readBody(res);
  if (res.status === 409) return { outcome: "claimed" };
  if (!res.ok) throw parseApiError(res.status, body, res.headers.get("Retry-After"));
  const parsed = CreatedRunSchema.safeParse(body);
  return { outcome: "processed", status: parsed.success ? parsed.data.status : undefined };
}

/**
 * Processing requests started in this tab, by run id. The forge form starts
 * processing the moment the run is created (before navigating), and the run page
 * picks up the same promise instead of firing a second request.
 */
const inFlight = new Map<string, Promise<ProcessOutcome>>();

export function startProcessing(id: string, { force = false }: { force?: boolean } = {}): Promise<ProcessOutcome> {
  const existing = inFlight.get(id);
  if (existing && !force) return existing;
  const p = processRun(id);
  inFlight.set(id, p);
  // Keep the map for the session so a remount does not re-POST; drop failures so a retry can.
  p.catch(() => {
    if (inFlight.get(id) === p) inFlight.delete(id);
  });
  return p;
}

export function processingPromise(id: string): Promise<ProcessOutcome> | undefined {
  return inFlight.get(id);
}

/** Network failures and server errors (timeouts included) are worth a retry; 4xx are not. */
export function isRetryableProcessError(err: unknown): boolean {
  return err instanceof ApiError && (err.code === "network" || err.status >= 500);
}
