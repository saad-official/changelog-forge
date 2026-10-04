import { ArrowUpRightIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { CATEGORIES, type CategoryKey, type Ref, type Tone } from "@/lib/notes";

export const toneChip: Record<Tone, string> = {
  release: "border-release/35 bg-release-wash text-release-ink",
  signal: "border-signal/45 bg-signal-wash text-signal-ink",
  breaking: "border-breaking/35 bg-breaking-wash text-breaking-ink",
  neutral: "border-border bg-muted text-pencil",
};

export const toneMark: Record<Tone, string> = {
  release: "bg-release-wash text-release-ink",
  signal: "bg-signal-wash text-signal-ink",
  breaking: "bg-breaking-wash text-breaking-ink",
  neutral: "bg-muted text-pencil",
};

/** Category chip: the changelog's colour language in one pill. */
export function CategoryChip({ category, className }: { category: CategoryKey; className?: string }) {
  const c = CATEGORIES[category];
  return (
    <span
      className={cn(
        "figure inline-flex h-5 items-center gap-1 rounded-sm border px-1.5 text-[0.6875rem] font-semibold tracking-normal",
        toneChip[c.tone],
        className,
      )}
    >
      <span aria-hidden="true">{c.mark}</span>
      {c.chip}
    </span>
  );
}

export function PossiblyBreakingChip({ confidence }: { confidence?: number }) {
  return (
    <span className={cn("figure inline-flex h-5 items-center gap-1 rounded-sm border border-dashed px-1.5 text-[0.6875rem] font-semibold", toneChip.breaking)}>
      possibly breaking
      {confidence !== undefined ? <span className="font-normal">· {confidence.toFixed(2)}</span> : null}
    </span>
  );
}

/** Link chip to the source PR or commit, in mono. */
export function RefChip({ refItem }: { refItem: Ref }) {
  const what = refItem.kind === "pr" ? `pull request ${refItem.label}` : `commit ${refItem.label}`;
  return (
    <a
      href={refItem.url}
      target="_blank"
      rel="noreferrer noopener"
      className={cn(
        "figure group/ref inline-flex h-5 items-center gap-0.5 rounded-sm border border-border bg-sheet px-1.5 text-[0.6875rem] font-medium text-foreground/80 hover:border-foreground/40 hover:text-foreground motion-safe:transition-colors",
        refItem.kind === "pr" ? "" : "text-pencil",
      )}
      aria-label={`${what} on GitHub (opens in a new tab)`}
    >
      {refItem.label}
      <ArrowUpRightIcon className="size-2.5 opacity-50 group-hover/ref:opacity-100" aria-hidden="true" />
    </a>
  );
}

/** Render `backtick` spans in model prose as inline code. */
export function InlineText({ text }: { text: string }) {
  const parts = text.split(/(`[^`]+`)/g);
  return (
    <>
      {parts.map((part, i) =>
        part.startsWith("`") && part.endsWith("`") && part.length > 2 ? (
          <code key={i} className="figure rounded-[3px] bg-muted px-1 py-px text-[0.85em] break-words">
            {part.slice(1, -1)}
          </code>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  );
}
