"use client";

import Link from "next/link";
import { ArrowUpRightIcon, RotateCcwIcon, TriangleAlertIcon } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { UsageCard } from "@/components/notes/usage-card";
import { VerificationPanel } from "@/components/notes/verification-panel";
import { cn } from "@/lib/utils";
import { isTerminal, type RunDetail } from "@/lib/api";
import { errorTitle } from "@/lib/errors";
import { formatCount, formatDuration, rangeLabel } from "@/lib/format";
import { deriveProgress } from "@/lib/progress";
import { ctaPrimary, ctaSecondary } from "@/lib/site";
import { Documents } from "./documents";
import { ProgressLog } from "./progress-log";
import { StageTrack } from "./stage-track";
import { useRun, type ProcessState } from "./use-run";

function againHref(run: RunDetail) {
  const q = new URLSearchParams({ repo: run.repo, base: run.base, head: run.head });
  if (run.audiences.length > 0) q.set("audiences", run.audiences.join(","));
  return `/forge?${q.toString()}`;
}

const statusStyle = {
  running: "border-signal/50 bg-signal-wash text-signal-ink",
  done: "border-release/40 bg-release-wash text-release-ink",
  failed: "border-breaking/40 bg-breaking-wash text-breaking-ink",
};

export function RunView({ id }: { id: string }) {
  const { run, loadError, events, connection, processState, retryProcessing } = useRun(id);
  const progress = deriveProgress(events, run?.status);
  const status = run && isTerminal(run.status) ? run.status : progress.status;
  const terminal = isTerminal(status);
  const tone = status === "done" ? "done" : status === "failed" ? "failed" : "running";

  if (loadError && !run) {
    return (
      <div className="mx-auto max-w-xl space-y-4 py-10">
        <h1 className="text-3xl font-extrabold [font-stretch:92%]">{errorTitle(loadError)}</h1>
        <p className="text-muted-foreground">{loadError.message}</p>
        <p className="figure text-sm text-muted-foreground">run {id}</p>
        <Link href="/forge" className={ctaPrimary}>
          Start a new run
        </Link>
      </div>
    );
  }

  const repo = run?.repo ?? "";
  const commits = run?.commit_count || progress.commitCount || 0;
  const groups = run?.group_count || progress.groupCount || 0;
  const duration =
    run?.created_at && run.finished_at ? formatDuration(Date.parse(run.finished_at) - Date.parse(run.created_at)) : "";
  const command = run ? `changelog-forge ${run.repo} ${rangeLabel(run.base, run.head)} --audience ${(run.audiences.length ? run.audiences : ["user", "dev"]).join(",")}` : `changelog-forge run ${id}`;
  const outputsReady = !!run && status === "done" && !!(run.outputs.user || run.outputs.dev);

  return (
    <div className="space-y-6">
      {/* Run header */}
      <div className="flex flex-col gap-4 border-b border-border pb-6 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0 space-y-2">
          <p className="hunk">@@ run {id} @@</p>
          {run ? (
            <h1 className="text-3xl leading-tight font-extrabold break-words [font-stretch:92%] sm:text-4xl">
              {repo}{" "}
              <span className="figure block text-xl font-medium tracking-normal text-muted-foreground sm:inline sm:text-2xl">
                {rangeLabel(run.base, run.head)}
              </span>
            </h1>
          ) : (
            <>
              <h1 className="sr-only">Loading run {id}</h1>
              <Skeleton className="h-10 w-72 max-w-full" />
            </>
          )}
          <dl className="figure flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground">
            <div className="flex items-center gap-1.5">
              <dt className="sr-only">Status</dt>
              <dd className={cn("inline-flex h-6 items-center gap-1.5 rounded-sm border px-2 text-xs font-semibold", statusStyle[tone])}>
                {tone === "running" ? <span aria-hidden="true" className="size-1.5 rounded-full bg-current motion-safe:animate-pulse" /> : null}
                {status}
              </dd>
            </div>
            <div className="flex gap-1">
              <dt>commits</dt>
              <dd className="text-foreground">{formatCount(commits)}</dd>
            </div>
            <div className="flex gap-1">
              <dt>groups</dt>
              <dd className="text-foreground">{formatCount(groups)}</dd>
            </div>
            {duration ? (
              <div className="flex gap-1">
                <dt>took</dt>
                <dd className="text-foreground">{duration}</dd>
              </div>
            ) : null}
          </dl>
        </div>
        {run ? (
          <div className="flex flex-wrap gap-2">
            <a href={`https://github.com/${run.repo}/compare/${encodeURIComponent(run.base)}...${encodeURIComponent(run.head)}`} className={cn(ctaSecondary, "h-10 px-4 text-sm")}>
              Compare on GitHub
              <ArrowUpRightIcon className="size-4" aria-hidden="true" />
            </a>
            <Link href={againHref(run)} className={cn(ctaPrimary, "h-10 px-4 text-sm")}>
              <RotateCcwIcon className="size-4" aria-hidden="true" />
              Run again
            </Link>
          </div>
        ) : null}
      </div>

      <ProcessBanner state={processState} terminal={terminal} onRetry={retryProcessing} />

      <StageTrack progress={{ ...progress, status, failedStage: status === "failed" ? (progress.failedStage ?? 0) : undefined }} />

      {status === "failed" ? (
        <div role="alert" className="flex gap-3 rounded-lg border border-breaking/40 bg-breaking-wash p-4 text-breaking-ink">
          <TriangleAlertIcon className="mt-0.5 size-5 shrink-0" aria-hidden="true" />
          <div className="min-w-0 space-y-1">
            <h2 className="font-bold">The run failed</h2>
            <p className="text-sm break-words text-foreground/90">{run?.error ?? "The API reported a failure without a message. The log below has the last steps."}</p>
            {run ? (
              <Link href={againHref(run)} className="inline-block pt-1 text-sm font-semibold underline underline-offset-4">
                Try the same range again
              </Link>
            ) : null}
          </div>
        </div>
      ) : null}

      {outputsReady && run ? (
        <>
          <Documents run={run} />
          <div className="grid items-start gap-5 lg:grid-cols-2">
            <VerificationPanel verified={run.verified} repo={run.repo} commitCount={commits} />
            <UsageCard usage={run.usage} commitCount={commits} />
          </div>
          <ProgressLog events={events} command={command} connection={connection} running={false} />
        </>
      ) : (
        <>
          <ProgressLog events={events} command={command} connection={connection} running={!terminal} />
          {!terminal ? <PendingDocuments /> : null}
          {status === "failed" && run && run.usage.usd > 0 ? (
            <div className="max-w-md">
              <UsageCard usage={run.usage} commitCount={commits} />
            </div>
          ) : null}
          {status === "done" && !outputsReady ? (
            <p className="text-sm text-muted-foreground" role="status">
              Run finished; fetching the documents…
            </p>
          ) : null}
        </>
      )}
    </div>
  );
}

function ProcessBanner({ state, terminal, onRetry }: { state: ProcessState; terminal: boolean; onRetry: () => void }) {
  if (state.state !== "error" || terminal) return null;
  return (
    <div role="alert" className="flex flex-col gap-3 rounded-lg border border-signal/50 bg-signal-wash p-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0 space-y-0.5">
        <h2 className="font-bold text-signal-ink">{state.retryable ? "Processing did not start" : errorTitle(state.error)}</h2>
        <p className="text-sm break-words text-foreground/85">{state.error.message}</p>
      </div>
      {state.retryable ? (
        <button type="button" onClick={onRetry} className={cn(ctaPrimary, "h-10 shrink-0 px-4 text-sm")}>
          <RotateCcwIcon className="size-4" aria-hidden="true" />
          Retry processing
        </button>
      ) : null}
    </div>
  );
}

/** Two blank sheets where the documents will land. */
function PendingDocuments() {
  return (
    <div className="grid gap-5 lg:grid-cols-2" aria-hidden="true">
      {["user.md", "dev.md"].map((f) => (
        <div key={f} className="ruled rounded-lg border border-dashed border-border bg-sheet/60 p-5">
          <p className="figure text-xs text-muted-foreground">{f}</p>
          <div className="mt-5 space-y-3">
            <Skeleton className="h-5 w-2/3" />
            <Skeleton className="h-3.5 w-full" />
            <Skeleton className="h-3.5 w-5/6" />
            <Skeleton className="mt-6 h-4 w-1/3" />
            <Skeleton className="h-3.5 w-full" />
            <Skeleton className="h-3.5 w-4/5" />
          </div>
        </div>
      ))}
    </div>
  );
}
