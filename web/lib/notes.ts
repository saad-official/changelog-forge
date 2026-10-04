/**
 * Normalise the API's `ReleaseNotes` JSON into what the documents render.
 *
 * Expected shape (one per audience):
 *   { intro, sections: [{ category, title?, prose?, items: [{ summary, category?, breaking?,
 *     breaking_confidence?, possibly_breaking?, migration_note?, refs: [...] }] }] }
 * Also accepted: a flat `items` list grouped here by category, and refs given as
 * "#123" / "abc1234" strings, numbers, GitHub URLs or { kind, id, url } objects.
 */

export type CategoryKey = "breaking" | "features" | "fixes" | "performance" | "docs" | "internal";
export type Tone = "breaking" | "release" | "signal" | "neutral";

export const CATEGORY_ORDER: CategoryKey[] = ["breaking", "features", "fixes", "performance", "docs", "internal"];

export const CATEGORIES: Record<CategoryKey, { label: string; chip: string; tone: Tone; mark: string }> = {
  breaking: { label: "Breaking changes", chip: "breaking", tone: "breaking", mark: "!" },
  features: { label: "Features", chip: "feature", tone: "release", mark: "+" },
  fixes: { label: "Fixes", chip: "fix", tone: "signal", mark: "~" },
  performance: { label: "Performance", chip: "perf", tone: "signal", mark: "»" },
  docs: { label: "Docs", chip: "docs", tone: "neutral", mark: "§" },
  internal: { label: "Internal", chip: "internal", tone: "neutral", mark: "·" },
};

export function toCategory(raw: unknown): CategoryKey {
  const s = String(raw ?? "").toLowerCase().trim();
  if (s.startsWith("break")) return "breaking";
  if (s.startsWith("feat") || s === "added" || s === "new" || s.startsWith("enhance")) return "features";
  if (s.startsWith("fix") || s.startsWith("bug")) return "fixes";
  if (s.startsWith("perf")) return "performance";
  if (s.startsWith("doc")) return "docs";
  return "internal";
}

export type RefKind = "pr" | "commit";
export type Ref = { kind: RefKind; id: string; label: string; url: string };

const SHA_RE = /^[0-9a-f]{7,40}$/i;

function safeHttpUrl(u: unknown): string | undefined {
  if (typeof u !== "string") return undefined;
  try {
    const url = new URL(u);
    return url.protocol === "https:" || url.protocol === "http:" ? url.toString() : undefined;
  } catch {
    return undefined;
  }
}

function build(kind: RefKind, id: string, repo: string, url?: string): Ref {
  const base = `https://github.com/${repo}`;
  return kind === "pr"
    ? { kind, id, label: `#${id}`, url: url ?? `${base}/pull/${id}` }
    : { kind, id, label: id.slice(0, 7), url: url ?? `${base}/commit/${id}` };
}

/** One reference to a link chip, or null when it cannot be read. */
export function toRef(raw: unknown, repo: string): Ref | null {
  if (typeof raw === "number" && Number.isInteger(raw) && raw > 0) return build("pr", String(raw), repo);
  if (typeof raw === "string") {
    const s = raw.trim();
    const pr = s.match(/^(?:#|pr\s*#?)(\d{1,7})$/i) ?? s.match(/^(\d{1,7})$/);
    if (pr) return build("pr", pr[1], repo);
    if (SHA_RE.test(s)) return build("commit", s.toLowerCase(), repo);
    const url = safeHttpUrl(s);
    if (url) {
      const m = url.match(/github\.com\/[^/]+\/[^/]+\/(pull|commit)\/([0-9a-f]+)/i);
      if (m) return build(m[1].toLowerCase() === "pull" ? "pr" : "commit", m[2].toLowerCase(), repo, url);
    }
    return null;
  }
  if (typeof raw === "object" && raw !== null) {
    const o = raw as Record<string, unknown>;
    const kindRaw = String(o.kind ?? o.type ?? "").toLowerCase();
    const id = o.id ?? o.number ?? o.sha ?? o.ref ?? o.pr;
    const url = safeHttpUrl(o.url ?? o.html_url);
    if (kindRaw.startsWith("pr") || kindRaw.startsWith("pull") || typeof o.number === "number" || o.pr !== undefined) {
      const n = String(id ?? "").replace(/^#/, "");
      return /^\d+$/.test(n) ? build("pr", n, repo, url) : null;
    }
    if (kindRaw.startsWith("commit") || kindRaw === "sha" || typeof o.sha === "string") {
      const sha = String(id ?? "");
      return SHA_RE.test(sha) ? build("commit", sha.toLowerCase(), repo, url) : null;
    }
    return id !== undefined ? toRef(id, repo) : null;
  }
  return null;
}

export type NoteItem = {
  summary: string;
  category: CategoryKey;
  breaking: boolean;
  possiblyBreaking: boolean;
  confidence?: number;
  migration?: string;
  refs: Ref[];
};
export type NoteSection = { category: CategoryKey; title: string; prose?: string; items: NoteItem[] };
export type Notes = { title?: string; intro?: string; sections: NoteSection[] };

function text(...vals: unknown[]): string | undefined {
  for (const v of vals) if (typeof v === "string" && v.trim() !== "") return v.trim();
  return undefined;
}

function numberOrUndefined(v: unknown): number | undefined {
  return typeof v === "number" && Number.isFinite(v) ? v : undefined;
}

function toItem(raw: unknown, repo: string, sectionCategory?: CategoryKey): NoteItem | null {
  if (typeof raw === "string") {
    return { summary: raw, category: sectionCategory ?? "internal", breaking: sectionCategory === "breaking", possiblyBreaking: false, refs: [] };
  }
  if (typeof raw !== "object" || raw === null) return null;
  const o = raw as Record<string, unknown>;
  const summary = text(o.summary, o.text, o.title, o.description, o.user_summary, o.dev_summary);
  if (!summary) return null;

  const refsRaw: unknown[] = [];
  for (const key of ["refs", "links", "references", "prs", "commits", "shas"]) {
    const v = o[key];
    if (Array.isArray(v)) refsRaw.push(...v);
  }
  for (const key of ["pr", "pr_number", "sha", "commit"]) if (o[key] !== undefined && o[key] !== null) refsRaw.push(key.startsWith("pr") ? `#${String(o[key]).replace(/^#/, "")}` : o[key]);
  const seen = new Set<string>();
  const refs: Ref[] = [];
  for (const r of refsRaw) {
    const ref = toRef(r, repo);
    if (ref && !seen.has(`${ref.kind}:${ref.id}`)) {
      seen.add(`${ref.kind}:${ref.id}`);
      refs.push(ref);
    }
  }
  // PRs first, then commits: the PR is the better link for a reader.
  refs.sort((a, b) => (a.kind === b.kind ? 0 : a.kind === "pr" ? -1 : 1));

  const category = o.category !== undefined ? toCategory(o.category) : (sectionCategory ?? "internal");
  const status = String(o.status ?? o.breaking_status ?? "").toLowerCase();
  const possiblyBreaking = o.possibly_breaking === true || status.includes("possibly");
  const breaking = !possiblyBreaking && (o.breaking === true || category === "breaking" || sectionCategory === "breaking");
  return {
    summary,
    category: breaking ? "breaking" : category === "breaking" ? "internal" : category,
    breaking,
    possiblyBreaking,
    confidence: numberOrUndefined(o.breaking_confidence) ?? numberOrUndefined(o.confidence),
    migration: text(o.migration_note, o.migration),
    refs,
  };
}

export function normaliseNotes(json: unknown, repo: string): Notes | null {
  if (typeof json === "string") {
    try {
      return normaliseNotes(JSON.parse(json), repo);
    } catch {
      return null;
    }
  }
  if (typeof json !== "object" || json === null) return null;
  const o = json as Record<string, unknown>;
  const buckets = new Map<CategoryKey, NoteSection>();
  const bucket = (c: CategoryKey) => {
    let s = buckets.get(c);
    if (!s) {
      s = { category: c, title: CATEGORIES[c].label, items: [] };
      buckets.set(c, s);
    }
    return s;
  };

  if (Array.isArray(o.sections)) {
    for (const raw of o.sections) {
      if (typeof raw !== "object" || raw === null) continue;
      const s = raw as Record<string, unknown>;
      const category = toCategory(s.category ?? s.key ?? s.name ?? s.title);
      const target = bucket(category);
      const title = text(s.title, s.heading);
      if (title) target.title = title;
      const prose = text(s.prose, s.body, s.summary, s.intro);
      if (prose) target.prose = target.prose ? `${target.prose}\n\n${prose}` : prose;
      for (const it of Array.isArray(s.items) ? s.items : []) {
        const item = toItem(it, repo, category);
        if (item) target.items.push(item);
      }
    }
  }
  if (Array.isArray(o.items)) {
    for (const it of o.items) {
      const item = toItem(it, repo);
      if (item) bucket(item.category).items.push(item);
    }
  }
  if (o.categories && typeof o.categories === "object" && !Array.isArray(o.categories)) {
    for (const [key, list] of Object.entries(o.categories as Record<string, unknown>)) {
      const category = toCategory(key);
      for (const it of Array.isArray(list) ? list : []) {
        const item = toItem(it, repo, category);
        if (item) bucket(category).items.push(item);
      }
    }
  }

  const sections = CATEGORY_ORDER.map((c) => buckets.get(c)).filter((s): s is NoteSection => !!s && (s.items.length > 0 || !!s.prose));
  const intro = text(o.intro, o.summary, o.overview, o.lede);
  if (sections.length === 0 && !intro) return null;
  return { title: text(o.title, o.heading), intro, sections };
}

export function countByCategory(notes: Notes): Partial<Record<CategoryKey, number>> {
  const out: Partial<Record<CategoryKey, number>> = {};
  for (const s of notes.sections) out[s.category] = (out[s.category] ?? 0) + s.items.length;
  return out;
}

export function countItems(notes: Notes): number {
  return notes.sections.reduce((n, s) => n + s.items.length, 0);
}

/** GitHub-flavoured Markdown, the same layout the API renders. Used when the API sent JSON but no Markdown. */
export function notesToMarkdown(notes: Notes, opts: { heading?: string } = {}): string {
  const lines: string[] = [];
  const heading = opts.heading ?? notes.title;
  if (heading) lines.push(`# ${heading}`, "");
  if (notes.intro) lines.push(notes.intro, "");
  for (const s of notes.sections) {
    lines.push(`## ${s.title}`, "");
    if (s.prose) lines.push(s.prose, "");
    for (const item of s.items) {
      const links = item.refs.map((r) => `[${r.label}](${r.url})`).join(", ");
      const flag = item.possiblyBreaking ? " _(possibly breaking)_" : "";
      lines.push(`- ${item.summary}${flag}${links ? ` (${links})` : ""}`);
      if (item.migration) lines.push(`  - Migration: ${item.migration}`);
    }
    lines.push("");
  }
  return `${lines.join("\n").trimEnd()}\n`;
}
