/** Formatting and input parsing shared by the form, the run page and tests. */

const OWNER = "[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})";
const NAME = "[A-Za-z0-9._-]{1,100}";
const REPO_RE = new RegExp(`^(${OWNER})/(${NAME})$`);

export type ParsedRepoInput = {
  /** `owner/name`, when the input could be read. */
  repo?: string;
  /** Refs found in a compare URL or an inline `base..head`. */
  base?: string;
  head?: string;
  /** Whether the input was a GitHub URL (repo or compare). */
  fromUrl: boolean;
  error?: string;
};

function splitRange(range: string): { base?: string; head?: string } {
  const decoded = safeDecode(range);
  const sep = decoded.includes("...") ? "..." : decoded.includes("..") ? ".." : null;
  if (!sep) return {};
  const [base, head] = decoded.split(sep, 2);
  return { base: base?.trim() || undefined, head: head?.trim() || undefined };
}

function safeDecode(s: string): string {
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
}

/**
 * Accepts `owner/name`, `owner/name@base..head`, `https://github.com/owner/name`
 * and `https://github.com/owner/name/compare/base...head` (two or three dots).
 */
export function parseRepoInput(input: string): ParsedRepoInput {
  let value = input.trim();
  if (value === "") return { fromUrl: false, error: "Enter a repository as owner/name or a GitHub compare URL." };

  const urlMatch = value.match(/^(?:https?:\/\/)?(?:www\.)?github\.com\/(.+)$/i);
  if (urlMatch) {
    const path = urlMatch[1].replace(/[?#].*$/, "").replace(/\/+$/, "");
    const parts = path.split("/");
    if (parts.length < 2) return { fromUrl: true, error: "That GitHub URL has no repository in it." };
    const repo = `${parts[0]}/${parts[1].replace(/\.git$/i, "")}`;
    if (!REPO_RE.test(repo)) return { fromUrl: true, error: "That GitHub URL does not name a valid repository." };
    if (parts[2] === "compare" && parts.length > 3) {
      const { base, head } = splitRange(parts.slice(3).join("/"));
      if (!base || !head) return { repo, fromUrl: true, error: "The compare URL needs both refs, like v1.2.0...v1.3.0." };
      return { repo, base, head, fromUrl: true };
    }
    return { repo, fromUrl: true };
  }

  let range: { base?: string; head?: string } = {};
  const at = value.indexOf("@");
  if (at > 0) {
    range = splitRange(value.slice(at + 1));
    value = value.slice(0, at);
  }
  value = value.replace(/\.git$/i, "");
  if (!REPO_RE.test(value)) {
    return { fromUrl: false, error: "Use owner/name (for example vercel/next.js) or paste a GitHub compare URL." };
  }
  return { repo: value, ...range, fromUrl: false };
}

/** Git refs: no spaces, no `..`, no control characters, not empty, <= 250 chars. */
export function refError(ref: string, which: "base" | "head"): string | undefined {
  const r = ref.trim();
  if (r === "") return `Enter the ${which} ref: a tag, branch or SHA.`;
  if (r.length > 250) return `The ${which} ref is too long.`;
  if (/\s/.test(r)) return `The ${which} ref cannot contain spaces.`;
  if (r.includes("..")) return `Put only one ref here; the range is base..head.`;
  if (/[\x00-\x1f\x7f~^:?*[\\]/.test(r)) return `The ${which} ref has a character git does not allow.`;
  return undefined;
}

const usdFull = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** Dollars at the precision LLM runs need: $0.0037, $0.042, $1.20. */
export function formatUsd(usd: number): string {
  if (!Number.isFinite(usd) || usd <= 0) return "$0.00";
  if (usd < 0.0001) return "<$0.0001";
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  if (usd < 1) return `$${usd.toFixed(3)}`;
  return usdFull.format(usd);
}

const int = new Intl.NumberFormat("en-US");
export function formatCount(n: number): string {
  return Number.isFinite(n) ? int.format(Math.round(n)) : "0";
}

/** `mm:ss.s` since the first event, the way a build log prints it. */
export function formatElapsed(ms: number): string {
  const safe = Math.max(0, Number.isFinite(ms) ? ms : 0);
  const totalTenths = Math.floor(safe / 100);
  const minutes = Math.floor(totalTenths / 600);
  const seconds = Math.floor((totalTenths % 600) / 10);
  const tenths = totalTenths % 10;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}.${tenths}`;
}

export function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  const m = Math.floor(ms / 60_000);
  const s = Math.round((ms % 60_000) / 1000);
  return `${m} min ${s} s`;
}

export function shortSha(sha: string): string {
  return sha.slice(0, 7);
}

export function rangeLabel(base: string, head: string): string {
  return `${base}..${head}`;
}

/** Cost per 100 commits, the unit the cost target is written in. */
export function usdPer100Commits(usd: number, commits: number): number | undefined {
  if (!commits || commits <= 0 || !Number.isFinite(usd)) return undefined;
  return (usd / commits) * 100;
}
