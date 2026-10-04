import { CheckIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Verified } from "@/lib/api";
import { formatCount } from "@/lib/format";
import { toRef } from "@/lib/notes";
import { RefChip } from "./chips";

const THRESHOLD = 0.6;

/** What the deterministic verifier removed or softened. Server-safe. */
export function VerificationPanel({
  verified,
  repo,
  commitCount,
  level = 2,
  className,
}: {
  verified: Verified;
  repo: string;
  commitCount: number;
  level?: 2 | 3;
  className?: string;
}) {
  const H = `h${level}` as const;
  const HS = `h${level + 1}` as "h3" | "h4";
  const clean = verified.dropped_refs.length === 0 && verified.downgraded.length === 0;

  return (
    <section aria-labelledby="verify-title" className={cn("min-w-0 rounded-lg border border-border bg-sheet p-4 sm:p-5", className)}>
      <H id="verify-title" className="text-base font-bold">
        Verification
      </H>
      <p className="mt-1 text-sm text-muted-foreground">
        {verified.checked_refs !== undefined ? (
          <>
            <span className="figure text-foreground">{formatCount(verified.checked_refs)}</span> references checked against{" "}
          </>
        ) : (
          "Every reference checked against "
        )}
        the <span className="figure text-foreground">{formatCount(commitCount)}</span> collected commits and their pull requests.
      </p>

      {clean ? (
        <p className="mt-4 flex items-center gap-2 text-sm">
          <CheckIcon className="size-4 text-release-ink" aria-hidden="true" />
          Nothing dropped, nothing downgraded.
        </p>
      ) : null}

      {verified.dropped_refs.length > 0 ? (
        <div className="mt-4 space-y-2">
          <HS className="text-sm font-semibold">
            Dropped <span className="figure font-normal text-muted-foreground">{verified.dropped_refs.length}</span>
          </HS>
          <p className="text-xs text-muted-foreground">Referenced by the model, not in the input. Removed from both documents.</p>
          <ul className="flex flex-wrap gap-1.5">
            {verified.dropped_refs.map((r) => (
              <li key={r}>
                <span className="figure inline-flex h-6 items-center rounded-sm border border-breaking/35 bg-breaking-wash px-2 text-xs text-breaking-ink line-through decoration-2">
                  <span className="sr-only">dropped reference </span>
                  {r}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {verified.downgraded.length > 0 ? (
        <div className="mt-5 space-y-2">
          <HS className="text-sm font-semibold">
            Downgraded <span className="figure font-normal text-muted-foreground">{verified.downgraded.length}</span>
          </HS>
          <p className="text-xs text-muted-foreground">
            Breaking claims below {THRESHOLD.toFixed(2)} confidence: &ldquo;possibly breaking&rdquo; in the dev notes, left out of the user notes.
          </p>
          <ul className="space-y-3">
            {verified.downgraded.map((d, i) => {
              const refs = d.refs.map((r) => toRef(r, repo)).filter((r) => r !== null);
              return (
                <li key={i} className="space-y-1.5 border-l-2 border-dashed border-breaking/50 pl-3">
                  <p className="text-sm leading-snug">{d.summary}</p>
                  <div className="flex flex-wrap items-center gap-2">
                    {refs.map((r) => (
                      <RefChip key={`${r.kind}:${r.id}`} refItem={r} />
                    ))}
                    {d.confidence !== undefined ? <ConfidenceMeter value={d.confidence} /> : null}
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

/** Confidence against the 0.60 threshold: a bar with a tick where the threshold sits. */
function ConfidenceMeter({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <span className="inline-flex items-center gap-2">
      <span className="relative h-1.5 w-20 rounded-full bg-muted" aria-hidden="true">
        <span className="absolute inset-y-0 left-0 rounded-full bg-breaking/70" style={{ width: `${pct}%` }} />
        <span className="absolute -top-1 -bottom-1 w-px bg-foreground/60" style={{ left: `${THRESHOLD * 100}%` }} />
      </span>
      <span className="figure text-xs">
        {value.toFixed(2)}
        <span className="text-muted-foreground"> &lt; {THRESHOLD.toFixed(2)}</span>
      </span>
    </span>
  );
}
