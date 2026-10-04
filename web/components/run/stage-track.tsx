import { cn } from "@/lib/utils";
import { STAGES, type Progress } from "@/lib/progress";

/** collect → group → map → reduce → verify → render, with the current stage marked. */
export function StageTrack({ progress, className }: { progress: Progress; className?: string }) {
  return (
    <ol className={cn("figure grid grid-cols-3 gap-px overflow-hidden rounded-lg border border-border bg-border text-xs sm:grid-cols-6", className)} aria-label="Pipeline stages">
      {STAGES.map((stage, i) => {
        const failedHere = progress.failedStage === i;
        const done = !failedHere && (progress.stage > i || progress.stage === 6);
        const current = !failedHere && !done && progress.stage === i && progress.status !== "failed";
        const state = failedHere ? "failed" : done ? "done" : current ? "running" : "pending";
        const detail =
          stage === "map" && progress.mapGroup && (current || done)
            ? `${progress.mapGroup.k}/${progress.mapGroup.m}`
            : stage === "collect" && progress.commitCount
              ? `${progress.commitCount}`
              : stage === "group" && progress.groupCount
                ? `${progress.groupCount}`
                : null;
        return (
          <li
            key={stage}
            aria-current={current ? "step" : undefined}
            className={cn(
              "flex items-center justify-between gap-2 bg-sheet px-3 py-2.5",
              done && "text-foreground",
              current && "bg-signal-wash text-signal-ink",
              failedHere && "bg-breaking-wash text-breaking-ink",
              state === "pending" && "text-muted-foreground",
            )}
          >
            <span className="flex items-center gap-1.5">
              <span aria-hidden="true" className="w-3 text-center">
                {done ? "✓" : failedHere ? "✗" : current ? <span className="motion-safe:animate-pulse">●</span> : "○"}
              </span>
              {stage}
              <span className="sr-only">: {state}</span>
            </span>
            {detail ? <span className="tabular-nums opacity-80">{detail}</span> : null}
          </li>
        );
      })}
    </ol>
  );
}
