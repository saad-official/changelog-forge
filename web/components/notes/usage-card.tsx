import { cn } from "@/lib/utils";
import type { Usage } from "@/lib/api";
import { formatCount, formatUsd, usdPer100Commits } from "@/lib/format";

/** Tokens and dollars at paid rates, by model. Server-safe. */
export function UsageCard({
  usage,
  commitCount,
  level = 2,
  className,
  pending = false,
}: {
  usage: Usage;
  commitCount: number;
  level?: 2 | 3;
  className?: string;
  pending?: boolean;
}) {
  const H = `h${level}` as const;
  const per100 = usdPer100Commits(usage.usd, commitCount);
  const ceiling = usage.max_usd && usage.max_usd > 0 ? Math.min(1, usage.usd / usage.max_usd) : undefined;

  return (
    <section aria-labelledby="usage-title" className={cn("min-w-0 rounded-lg border border-border bg-sheet p-4 sm:p-5", className)}>
      <div className="flex items-baseline justify-between gap-3">
        <H id="usage-title" className="text-base font-bold">
          Cost of this run
        </H>
        <span className="text-xs text-muted-foreground">at paid rates</span>
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3">
        <div className="col-span-2">
          <dt className="sr-only">Total cost</dt>
          <dd className="figure text-3xl font-semibold tracking-tight">{pending ? "…" : formatUsd(usage.usd)}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Tokens in</dt>
          <dd className="figure text-sm">{formatCount(usage.prompt_tokens)}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Tokens out</dt>
          <dd className="figure text-sm">{formatCount(usage.completion_tokens)}</dd>
        </div>
        {per100 !== undefined && !pending ? (
          <div>
            <dt className="text-xs text-muted-foreground">Per 100 commits</dt>
            <dd className="figure text-sm">{formatUsd(per100)}</dd>
          </div>
        ) : null}
        {ceiling !== undefined ? (
          <div>
            <dt className="text-xs text-muted-foreground">Of the {formatUsd(usage.max_usd!)} ceiling</dt>
            <dd className="mt-1.5 flex items-center gap-2">
              <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted" aria-hidden="true">
                <span className="block h-full rounded-full bg-foreground/70" style={{ width: `${Math.max(2, ceiling * 100)}%` }} />
              </span>
              <span className="figure text-xs">{Math.round(ceiling * 100)}%</span>
            </dd>
          </div>
        ) : null}
      </dl>

      {usage.by_model.length > 0 ? (
        <div className="mt-4 overflow-x-auto border-t border-border pt-3">
          <table className="w-full min-w-[18rem] text-left text-xs">
            <caption className="sr-only">Usage by model</caption>
            <thead className="text-muted-foreground">
              <tr>
                <th scope="col" className="pb-1.5 font-medium">
                  Model
                </th>
                <th scope="col" className="pb-1.5 text-right font-medium">
                  Tokens
                </th>
                <th scope="col" className="pb-1.5 text-right font-medium">
                  Cost
                </th>
              </tr>
            </thead>
            <tbody className="figure">
              {usage.by_model.map((m) => (
                <tr key={`${m.model}-${m.stage ?? ""}`} className="border-t border-border/60 align-top">
                  <th scope="row" className="py-1.5 pr-2 font-normal">
                    <span className="break-all">{m.model}</span>
                    <span className="block text-[0.6875rem] text-muted-foreground">
                      {[m.stage, m.calls !== undefined ? `${m.calls} call${m.calls === 1 ? "" : "s"}` : null].filter(Boolean).join(" · ")}
                    </span>
                  </th>
                  <td className="py-1.5 text-right whitespace-nowrap">
                    {formatCount(m.prompt_tokens)}
                    <span className="text-muted-foreground"> / </span>
                    {formatCount(m.completion_tokens)}
                  </td>
                  <td className="py-1.5 pl-2 text-right">{formatUsd(m.usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}
