/**
 * Errors from the Changelog Forge API, normalised from whatever JSON shape the
 * server sent. FastAPI's defaults are `{ detail: string }` and, for request
 * validation, `{ detail: [{ loc, msg, type }] }`. The preferred shape for
 * domain errors is `{ detail: { code, message, retry_after?, limit? } }`, and a
 * flat `{ code, message }` or `{ error: { code, message } }` is accepted too.
 */

export type ApiErrorCode =
  | "rate_limited"
  | "commit_cap"
  | "repo_not_found"
  | "range_not_found"
  | "validation"
  | "unauthorized"
  | "budget_exceeded"
  | "run_not_found"
  | "network"
  | "server"
  | "unknown";

export type FieldName = "repo" | "base" | "head" | "audiences" | "github_token";

export class ApiError extends Error {
  readonly status: number;
  readonly code: ApiErrorCode;
  /** Seconds until a rate-limited client may retry, when the server said so. */
  readonly retryAfter?: number;
  /** Field-level messages from request validation, keyed by body field. */
  readonly fields: Partial<Record<FieldName, string>>;

  constructor(opts: {
    status: number;
    code: ApiErrorCode;
    message: string;
    retryAfter?: number;
    fields?: Partial<Record<FieldName, string>>;
  }) {
    super(opts.message);
    this.name = "ApiError";
    this.status = opts.status;
    this.code = opts.code;
    this.retryAfter = opts.retryAfter;
    this.fields = opts.fields ?? {};
  }
}

const KNOWN_CODES = new Set<ApiErrorCode>([
  "rate_limited",
  "commit_cap",
  "repo_not_found",
  "range_not_found",
  "validation",
  "unauthorized",
  "budget_exceeded",
  "run_not_found",
]);

const FIELD_NAMES = new Set<FieldName>(["repo", "base", "head", "audiences", "github_token"]);

type Json = unknown;

function isRecord(v: Json): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function str(v: unknown): string | undefined {
  return typeof v === "string" && v.trim() !== "" ? v : undefined;
}

function num(v: unknown): number | undefined {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim() !== "" && Number.isFinite(Number(v))) return Number(v);
  return undefined;
}

/** Guess a code from the status (and message) when the server did not send one. */
function codeFromStatus(status: number, message: string): ApiErrorCode {
  const m = message.toLowerCase();
  if (status === 429) return "rate_limited";
  if (status === 401 || status === 403) return "unauthorized";
  if (status === 404) {
    if (m.includes("run")) return "run_not_found";
    if (m.includes("ref") || m.includes("range") || m.includes("tag") || m.includes("branch")) return "range_not_found";
    return "repo_not_found";
  }
  if (status === 413 || ((status === 400 || status === 422) && m.includes("commit") && (m.includes("cap") || m.includes("limit") || m.includes("400")))) {
    return "commit_cap";
  }
  if (status === 400 || status === 422) return "validation";
  if (status >= 500) return "server";
  return "unknown";
}

function defaultMessage(code: ApiErrorCode, status: number): string {
  switch (code) {
    case "rate_limited":
      return "Too many runs from this address. The limit is 10 runs per hour.";
    case "commit_cap":
      return "That range has more commits than one run can take. Pick a smaller range.";
    case "repo_not_found":
      return "Repository not found, or it is private and no token was given.";
    case "range_not_found":
      return "One of the refs was not found in that repository.";
    case "unauthorized":
      return "GitHub refused the request. Check the token, or leave it empty for public repos.";
    case "budget_exceeded":
      return "The run hit its cost ceiling before finishing.";
    case "run_not_found":
      return "No run with that id. Runs are kept for 30 days.";
    case "server":
      return `The API returned an error (${status}). Try again in a minute.`;
    default:
      return `Request failed (${status}).`;
  }
}

/** Build an ApiError from a status, a parsed (or unparsable) body and an optional Retry-After header. */
export function parseApiError(status: number, body: Json, retryAfterHeader?: string | null): ApiError {
  let code: ApiErrorCode | undefined;
  let message: string | undefined;
  let retryAfter = num(retryAfterHeader ?? undefined);
  const fields: Partial<Record<FieldName, string>> = {};

  const readObject = (o: Record<string, unknown>) => {
    const c = str(o.code);
    if (c && KNOWN_CODES.has(c as ApiErrorCode)) code = c as ApiErrorCode;
    message = str(o.message) ?? str(o.msg) ?? str(o.detail) ?? message;
    retryAfter = num(o.retry_after) ?? num(o.retryAfter) ?? retryAfter;
  };

  if (isRecord(body)) {
    const detail = body.detail;
    if (typeof detail === "string") {
      message = detail;
    } else if (Array.isArray(detail)) {
      // FastAPI request validation: [{ loc: ["body", "base"], msg: "Field required" }]
      const msgs: string[] = [];
      for (const d of detail) {
        if (!isRecord(d)) continue;
        const msg = str(d.msg) ?? "Invalid value";
        const loc = Array.isArray(d.loc) ? d.loc.map(String) : [];
        const field = [...loc].reverse().find((l) => FIELD_NAMES.has(l as FieldName)) as FieldName | undefined;
        if (field && !fields[field]) fields[field] = msg;
        msgs.push(field ? `${field}: ${msg}` : msg);
      }
      message = msgs.length > 0 ? msgs.join("; ") : undefined;
      code = "validation";
    } else if (isRecord(detail)) {
      readObject(detail);
      const f = str(detail.field);
      if (f && FIELD_NAMES.has(f as FieldName) && message) fields[f as FieldName] = message;
    } else if (isRecord(body.error)) {
      readObject(body.error);
    } else {
      readObject(body);
    }
  } else if (typeof body === "string" && body.trim() !== "" && !body.trim().startsWith("<")) {
    message = body.trim().slice(0, 300);
  }

  const resolved = code ?? codeFromStatus(status, message ?? "");
  return new ApiError({
    status,
    code: resolved,
    message: message ?? defaultMessage(resolved, status),
    retryAfter,
    fields,
  });
}

export function networkError(apiUrl: string): ApiError {
  return new ApiError({
    status: 0,
    code: "network",
    message: `Could not reach the API at ${apiUrl}. It may be waking up (free hosting sleeps); try again in a few seconds.`,
  });
}

/** Short heading for an error box. */
export function errorTitle(err: ApiError): string {
  switch (err.code) {
    case "rate_limited":
      return "Rate limit reached";
    case "commit_cap":
      return "Range too large";
    case "repo_not_found":
      return "Repository not found";
    case "range_not_found":
      return "Ref not found";
    case "validation":
      return "Check the form";
    case "unauthorized":
      return "GitHub refused access";
    case "budget_exceeded":
      return "Cost ceiling reached";
    case "run_not_found":
      return "Run not found";
    case "network":
      return "API unreachable";
    case "server":
      return "API error";
    default:
      return "Something went wrong";
  }
}
