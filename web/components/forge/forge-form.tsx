"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { EyeIcon, EyeOffIcon, LoaderCircleIcon, TriangleAlertIcon } from "lucide-react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { createRun, startProcessing, type Audience } from "@/lib/api";
import { API_URL } from "@/lib/config";
import { ApiError, errorTitle, type FieldName } from "@/lib/errors";
import { parseRepoInput, refError } from "@/lib/format";
import { EXAMPLE_BASE, EXAMPLE_HEAD, EXAMPLE_REPO } from "@/lib/mock";

type Errors = Partial<Record<FieldName, string>>;

const fieldInput = "h-11 rounded-md bg-sheet px-3 text-[0.9375rem] md:text-[0.9375rem]";
const label = "block text-sm font-semibold";
const help = "mt-1.5 text-xs text-muted-foreground";
const errorText = "mt-1.5 text-sm font-medium text-breaking-ink";

const AUDIENCE_OPTIONS: { value: Audience; title: string; body: string }[] = [
  { value: "user", title: "Users", body: "What's new, in plain words. Possibly-breaking claims left out." },
  { value: "dev", title: "Developers", body: "Every change linked, breaking changes with confidence, migration notes." },
];

function retryHint(err: ApiError): string | null {
  if (err.code === "rate_limited" && err.retryAfter) {
    const minutes = Math.ceil(err.retryAfter / 60);
    return `You can start another run in about ${minutes} minute${minutes === 1 ? "" : "s"}.`;
  }
  if (err.code === "commit_cap") return "Try a narrower range: a patch release, or a SHA closer to head.";
  if (err.code === "repo_not_found") return "Check the spelling. For a private repository, add a token below.";
  if (err.code === "range_not_found") return "Use a tag, branch or SHA that exists in the repository.";
  if (err.code === "network") return `API: ${API_URL}`;
  return null;
}

export function ForgeForm({
  initial,
}: {
  initial: { repo: string; base: string; head: string; audiences: Audience[] };
}) {
  const router = useRouter();
  const [repo, setRepo] = useState(initial.repo);
  const [base, setBase] = useState(initial.base);
  const [head, setHead] = useState(initial.head);
  const [audiences, setAudiences] = useState<Audience[]>(initial.audiences);
  const [token, setToken] = useState("");
  const [showToken, setShowToken] = useState(false);
  const [errors, setErrors] = useState<Errors>({});
  const [apiError, setApiError] = useState<ApiError | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [fromUrl, setFromUrl] = useState(false);
  const alertRef = useRef<HTMLDivElement>(null);

  function onRepoChange(value: string) {
    setRepo(value);
    const parsed = parseRepoInput(value);
    if (parsed.base && parsed.head) {
      setBase(parsed.base);
      setHead(parsed.head);
      setFromUrl(true);
    } else {
      setFromUrl(false);
    }
    if (errors.repo) setErrors((e) => ({ ...e, repo: undefined }));
  }

  function validate(): { ok: true; repo: string } | { ok: false; errors: Errors } {
    const next: Errors = {};
    const parsed = parseRepoInput(repo);
    if (parsed.error || !parsed.repo) next.repo = parsed.error ?? "Enter a repository.";
    const b = refError(base, "base");
    const h = refError(head, "head");
    if (b) next.base = b;
    if (h) next.head = h;
    if (!b && !h && base.trim() === head.trim()) next.head = "Head must differ from base.";
    if (audiences.length === 0) next.audiences = "Pick at least one audience.";
    if (token.trim() !== "" && /\s/.test(token.trim())) next.github_token = "A token has no spaces.";
    return Object.keys(next).length > 0 || !parsed.repo ? { ok: false, errors: next } : { ok: true, repo: parsed.repo };
  }

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (submitting) return;
    setApiError(null);
    const v = validate();
    if (!v.ok) {
      setErrors(v.errors);
      const firstField = (["repo", "base", "head", "audiences", "github_token"] as const).find((f) => v.errors[f]);
      if (firstField) document.getElementById(firstField === "audiences" ? "audience-user" : `field-${firstField}`)?.focus();
      return;
    }
    setErrors({});
    setSubmitting(true);
    try {
      const created = await createRun({ repo: v.repo, base: base.trim(), head: head.trim(), audiences, github_token: token });
      // The API has no background worker: ask it to process now. Fire and forget;
      // the run page picks up this same request and offers a retry if it fails.
      void startProcessing(created.id).catch(() => {});
      setToken("");
      router.push(`/runs/${encodeURIComponent(created.id)}`);
    } catch (err) {
      const apiErr = err instanceof ApiError ? err : new ApiError({ status: 0, code: "unknown", message: String(err) });
      setApiError(apiErr);
      setErrors(apiErr.fields);
      setSubmitting(false);
      setTimeout(() => alertRef.current?.focus(), 0);
    }
  }

  function toggleAudience(a: Audience, checked: boolean) {
    setAudiences((prev) => (checked ? [...new Set([...prev, a])] : prev.filter((x) => x !== a)));
    if (errors.audiences) setErrors((e) => ({ ...e, audiences: undefined }));
  }

  const describedBy = (field: FieldName, helpId?: string) =>
    [helpId, errors[field] ? `${field}-error` : null].filter(Boolean).join(" ") || undefined;

  return (
    <form onSubmit={onSubmit} noValidate className="mt-8 space-y-7" aria-describedby={apiError ? "api-error" : undefined}>
      {apiError ? (
        <div
          ref={alertRef}
          id="api-error"
          role="alert"
          tabIndex={-1}
          className="flex gap-3 rounded-lg border border-breaking/40 bg-breaking-wash p-4 outline-none focus-visible:outline-2 focus-visible:outline-breaking"
        >
          <TriangleAlertIcon className="mt-0.5 size-5 shrink-0 text-breaking-ink" aria-hidden="true" />
          <div className="min-w-0 space-y-1">
            <p className="font-bold text-breaking-ink">
              {errorTitle(apiError)}
              {apiError.status ? <span className="figure ml-2 text-xs font-medium opacity-80">HTTP {apiError.status}</span> : null}
            </p>
            <p className="text-sm break-words">{apiError.message}</p>
            {retryHint(apiError) ? <p className="figure text-xs break-all text-muted-foreground">{retryHint(apiError)}</p> : null}
          </div>
        </div>
      ) : null}

      <div>
        <label htmlFor="field-repo" className={label}>
          Repository
        </label>
        <Input
          id="field-repo"
          name="repo"
          value={repo}
          onChange={(e) => onRepoChange(e.target.value)}
          placeholder="owner/name or a GitHub compare URL"
          autoComplete="off"
          autoCapitalize="none"
          spellCheck={false}
          inputMode="url"
          aria-invalid={!!errors.repo}
          aria-describedby={describedBy("repo", "repo-help")}
          className={cn(fieldInput, "figure")}
        />
        <p id="repo-help" className={help}>
          {fromUrl ? (
            <>Read base and head from the compare URL.</>
          ) : (
            <>
              For example <span className="figure">vercel/next.js</span>, or paste{" "}
              <span className="figure break-all">github.com/o/r/compare/v1...v2</span>.
            </>
          )}
        </p>
        {errors.repo ? (
          <p id="repo-error" className={errorText}>
            {errors.repo}
          </p>
        ) : null}
      </div>

      <div className="grid gap-5 sm:grid-cols-[1fr_auto_1fr] sm:items-start">
        <div className="min-w-0">
          <label htmlFor="field-base" className={label}>
            Base
          </label>
          <Input
            id="field-base"
            name="base"
            value={base}
            onChange={(e) => {
              setBase(e.target.value);
              if (errors.base) setErrors((x) => ({ ...x, base: undefined }));
            }}
            placeholder="v1.2.0"
            autoComplete="off"
            autoCapitalize="none"
            spellCheck={false}
            aria-invalid={!!errors.base}
            aria-describedby={describedBy("base", "base-help")}
            className={cn(fieldInput, "figure")}
          />
          <p id="base-help" className={help}>
            Older ref: tag, branch or SHA.
          </p>
          {errors.base ? (
            <p id="base-error" className={errorText}>
              {errors.base}
            </p>
          ) : null}
        </div>
        <span aria-hidden="true" className="figure hidden pt-9 text-muted-foreground sm:block">
          ..
        </span>
        <div className="min-w-0">
          <label htmlFor="field-head" className={label}>
            Head
          </label>
          <Input
            id="field-head"
            name="head"
            value={head}
            onChange={(e) => {
              setHead(e.target.value);
              if (errors.head) setErrors((x) => ({ ...x, head: undefined }));
            }}
            placeholder="v1.3.0"
            autoComplete="off"
            autoCapitalize="none"
            spellCheck={false}
            aria-invalid={!!errors.head}
            aria-describedby={describedBy("head", "head-help")}
            className={cn(fieldInput, "figure")}
          />
          <p id="head-help" className={help}>
            Newer ref. Notes cover base..head.
          </p>
          {errors.head ? (
            <p id="head-error" className={errorText}>
              {errors.head}
            </p>
          ) : null}
        </div>
      </div>

      <fieldset aria-describedby={errors.audiences ? "audiences-error" : undefined}>
        <legend className={label}>Audiences</legend>
        <div className="mt-2 grid gap-3 sm:grid-cols-2">
          {AUDIENCE_OPTIONS.map((o) => {
            const checked = audiences.includes(o.value);
            return (
              <label
                key={o.value}
                htmlFor={`audience-${o.value}`}
                className={cn(
                  "flex cursor-pointer gap-3 rounded-lg border bg-sheet p-3.5 motion-safe:transition-colors",
                  checked ? "border-foreground/50" : "border-border hover:border-foreground/30",
                )}
              >
                <input
                  id={`audience-${o.value}`}
                  type="checkbox"
                  name="audiences"
                  value={o.value}
                  checked={checked}
                  onChange={(e) => toggleAudience(o.value, e.target.checked)}
                  className="mt-0.5 size-4 shrink-0 accent-[var(--graphite)]"
                />
                <span className="min-w-0">
                  <span className="block text-sm font-semibold">
                    {o.title} <span className="figure text-xs font-normal text-muted-foreground">{o.value}.md</span>
                  </span>
                  <span className="mt-0.5 block text-xs text-muted-foreground">{o.body}</span>
                </span>
              </label>
            );
          })}
        </div>
        {errors.audiences ? (
          <p id="audiences-error" className={errorText}>
            {errors.audiences}
          </p>
        ) : null}
      </fieldset>

      <div>
        <label htmlFor="field-github_token" className={label}>
          GitHub token <span className="font-normal text-muted-foreground">(optional)</span>
        </label>
        <div className="relative">
          <Input
            id="field-github_token"
            name="github_token"
            type={showToken ? "text" : "password"}
            value={token}
            onChange={(e) => {
              setToken(e.target.value);
              if (errors.github_token) setErrors((x) => ({ ...x, github_token: undefined }));
            }}
            placeholder="github_pat_…"
            autoComplete="off"
            autoCapitalize="none"
            spellCheck={false}
            data-1p-ignore
            data-lpignore="true"
            aria-invalid={!!errors.github_token}
            aria-describedby={describedBy("github_token", "token-help")}
            className={cn(fieldInput, "figure pr-11")}
          />
          <button
            type="button"
            onClick={() => setShowToken((s) => !s)}
            className="absolute top-1/2 right-1 grid size-9 -translate-y-1/2 place-items-center rounded-md text-muted-foreground hover:text-foreground focus-visible:outline-2 focus-visible:outline-foreground"
            aria-label={showToken ? "Hide token" : "Show token"}
            aria-pressed={showToken}
          >
            {showToken ? <EyeOffIcon className="size-4" aria-hidden="true" /> : <EyeIcon className="size-4" aria-hidden="true" />}
          </button>
        </div>
        <p id="token-help" className={help}>
          <strong className="font-semibold text-foreground">Used for this run only, never stored.</strong> Only needed for
          private repositories, or to lift GitHub&rsquo;s limit of 60 requests an hour.
        </p>
        {errors.github_token ? (
          <p id="github_token-error" className={errorText}>
            {errors.github_token}
          </p>
        ) : null}
      </div>

      <div className="flex flex-col gap-4 border-t border-border pt-6 sm:flex-row sm:items-center">
        <button
          type="submit"
          disabled={submitting}
          className="inline-flex h-11 items-center justify-center gap-2 rounded-md bg-primary px-6 text-[0.9375rem] font-semibold text-primary-foreground hover:bg-primary/88 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-foreground disabled:opacity-70 motion-safe:transition-colors"
        >
          {submitting ? <LoaderCircleIcon className="size-4 motion-safe:animate-spin" aria-hidden="true" /> : null}
          {submitting ? "Starting run…" : "Forge release notes"}
        </button>
        <button
          type="button"
          onClick={() => {
            onRepoChange(EXAMPLE_REPO);
            setBase(EXAMPLE_BASE);
            setHead(EXAMPLE_HEAD);
            setErrors({});
          }}
          className="figure self-start rounded-sm text-left text-sm text-muted-foreground underline decoration-foreground/30 underline-offset-4 hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-foreground sm:self-auto"
        >
          try {EXAMPLE_REPO} {EXAMPLE_BASE}..{EXAMPLE_HEAD}
        </button>
      </div>
    </form>
  );
}
