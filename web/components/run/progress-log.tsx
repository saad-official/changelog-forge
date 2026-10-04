"use client";

import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import type { RunEvent } from "@/lib/api";
import { formatElapsed } from "@/lib/format";
import { lineTone, type LineTone } from "@/lib/progress";
import type { Connection } from "./use-run";

const toneClass: Record<LineTone, string> = {
  dim: "text-term-dim",
  plain: "text-term-fg",
  ok: "text-term-green",
  warn: "text-term-amber",
  error: "text-term-red",
};

const connectionLabel: Record<Connection, string> = {
  connecting: "connecting",
  live: "live",
  polling: "polling",
  closed: "complete",
};

function elapsedLabel(e: RunEvent, t0: number | undefined): string {
  const t = e.at ? Date.parse(e.at) : NaN;
  if (t0 === undefined || Number.isNaN(t)) return `#${String(e.seq).padStart(3, "0")}`;
  return formatElapsed(t - t0);
}

/** The progress stream, printed like a build log. */
export function ProgressLog({
  events,
  command,
  connection,
  running,
  className,
}: {
  events: RunEvent[];
  command: string;
  connection: Connection;
  running: boolean;
  className?: string;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  const firstAt = events.find((e) => e.at && !Number.isNaN(Date.parse(e.at)))?.at;
  const t0 = firstAt ? Date.parse(firstAt) : undefined;

  // Keep the newest line in view while the run is live (instant scroll; no animation to reduce).
  useEffect(() => {
    const el = scroller.current;
    if (el && running) el.scrollTop = el.scrollHeight;
  }, [events.length, running]);

  return (
    <section aria-labelledby="log-title" className={cn("min-w-0 overflow-hidden rounded-lg bg-term text-term-fg", className)}>
      <div className="flex items-center justify-between gap-3 border-b border-term-rule px-4 py-2">
        <h2 id="log-title" className="figure min-w-0 truncate text-xs font-normal tracking-normal text-term-dim">
          <span className="sr-only">Run log: </span>
          <span aria-hidden="true">$ </span>
          {command}
        </h2>
        <span className="figure flex shrink-0 items-center gap-1.5 text-xs text-term-dim">
          <span
            aria-hidden="true"
            className={cn(
              "size-1.5 rounded-full",
              connection === "live" ? "bg-term-green motion-safe:animate-pulse" : connection === "closed" ? "bg-term-dim" : "bg-term-amber",
            )}
          />
          {connectionLabel[connection]}
        </span>
      </div>
      <div ref={scroller} className="max-h-[22rem] overflow-y-auto px-4 py-3" tabIndex={0} aria-label="Run log, scrollable">
        <ol role="log" aria-live="polite" aria-relevant="additions" className="figure space-y-0.5 text-[0.8125rem] leading-relaxed">
          {events.map((e) => (
            <li key={e.seq} className="grid grid-cols-[auto_auto_1fr] gap-x-3">
              <span className="text-term-dim/80 tabular-nums select-none">{elapsedLabel(e, t0)}</span>
              <span className={cn("w-[6.5ch] select-none", toneClass[lineTone(e)] === toneClass.plain ? "text-term-dim" : toneClass[lineTone(e)])}>
                {e.kind}
              </span>
              <span className={cn("min-w-0 break-words", toneClass[lineTone(e)])}>{e.message || " "}</span>
            </li>
          ))}
          {running ? (
            <li className="grid grid-cols-[auto_1fr] gap-x-3" aria-hidden="true">
              <span className="text-term-dim/80">{events.length === 0 ? "00:00.0" : "       "}</span>
              <span>
                <span className="caret text-term-fg/80" />
              </span>
            </li>
          ) : null}
        </ol>
        {events.length === 0 && !running ? <p className="figure text-[0.8125rem] text-term-dim">No progress events recorded.</p> : null}
      </div>
    </section>
  );
}
