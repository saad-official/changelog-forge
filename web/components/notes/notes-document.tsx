import { cn } from "@/lib/utils";
import { CATEGORIES, countByCategory, type Notes } from "@/lib/notes";
import { CategoryChip, InlineText, PossiblyBreakingChip, RefChip, toneMark } from "./chips";

export const AUDIENCE_META = {
  user: { file: "user.md", title: "For users", blurb: "What's new, in plain words" },
  dev: { file: "dev.md", title: "For developers", blurb: "Every change, linked, with migration notes" },
} as const;

type Level = 2 | 3;

/**
 * One audience document on a sheet of paper. Server-safe (no hooks), so the
 * landing page renders the example statically and the run page reuses it.
 */
export function NotesDocument({
  notes,
  markdown,
  audience,
  level = 2,
  actions,
  className,
  idPrefix,
}: {
  notes: Notes | null;
  markdown?: string;
  audience: "user" | "dev";
  level?: Level;
  actions?: React.ReactNode;
  className?: string;
  idPrefix: string;
}) {
  const meta = AUDIENCE_META[audience];
  const H = `h${level}` as const;
  const HS = `h${level + 1}` as "h3" | "h4";
  const counts = notes ? countByCategory(notes) : {};
  const headingId = `${idPrefix}-${audience}-title`;

  return (
    <section
      aria-labelledby={headingId}
      className={cn("flex min-w-0 flex-col overflow-hidden rounded-lg border border-border bg-sheet shadow-sheet", className)}
    >
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-border bg-muted/60 px-4 py-2.5 sm:px-5">
        <span className="figure rounded-sm border border-border bg-sheet px-1.5 py-0.5 text-xs text-pencil">{meta.file}</span>
        <H id={headingId} className="text-[0.95rem] font-bold">
          {meta.title}
          <span className="sr-only">: {meta.blurb}</span>
        </H>
        <ul className="figure flex flex-wrap gap-2 text-xs" aria-label="Items by category">
          {Object.entries(counts).map(([key, n]) => {
            const c = CATEGORIES[key as keyof typeof CATEGORIES];
            return (
              <li key={key} className={cn("rounded-sm px-1", toneMark[c.tone])}>
                <span aria-hidden="true">
                  {c.mark}
                  {n}
                </span>
                <span className="sr-only">
                  {n} {c.label}
                </span>
              </li>
            );
          })}
        </ul>
        {actions ? <div className="ml-auto flex flex-wrap gap-1.5">{actions}</div> : null}
      </header>

      <div className="min-w-0 space-y-6 px-4 py-5 sm:px-6 sm:py-6">
        {notes ? (
          <>
            {notes.title || notes.intro ? (
              <div className="space-y-2">
                {notes.title ? <p className="font-heading text-xl font-extrabold tracking-tight [font-stretch:92%]">{notes.title}</p> : null}
                {notes.intro ? (
                  <p className="text-[0.9375rem] leading-relaxed text-foreground/85">
                    <InlineText text={notes.intro} />
                  </p>
                ) : null}
              </div>
            ) : null}

            {notes.sections.map((section) => {
              const c = CATEGORIES[section.category];
              return (
                <div key={section.category} className="space-y-3">
                  <HS className="flex items-center gap-2 text-sm font-bold tracking-tight uppercase">
                    <span aria-hidden="true" className={cn("figure grid size-5 place-items-center rounded-sm text-xs", toneMark[c.tone])}>
                      {c.mark}
                    </span>
                    {section.title}
                    <span className="figure text-xs font-normal text-pencil normal-case">{section.items.length}</span>
                  </HS>
                  {section.prose ? (
                    <p className="text-sm leading-relaxed text-foreground/85">
                      <InlineText text={section.prose} />
                    </p>
                  ) : null}
                  <ul className="divide-y divide-border/70 border-y border-border/70">
                    {section.items.map((item, i) => (
                      <li key={i} className="space-y-1.5 py-2.5">
                        <p className="text-[0.9375rem] leading-snug">
                          <InlineText text={item.summary} />
                        </p>
                        <div className="flex flex-wrap items-center gap-1.5">
                          <CategoryChip category={item.category} />
                          {item.possiblyBreaking ? <PossiblyBreakingChip confidence={item.confidence} /> : null}
                          {item.refs.map((r) => (
                            <RefChip key={`${r.kind}:${r.id}`} refItem={r} />
                          ))}
                        </div>
                        {item.migration ? (
                          <p className="border-l-2 border-breaking/60 pl-2.5 text-sm text-foreground/80">
                            <span className="font-semibold">Migration: </span>
                            <InlineText text={item.migration} />
                          </p>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                </div>
              );
            })}
          </>
        ) : markdown ? (
          // The API sent Markdown but no readable JSON: show it as written.
          <pre className="figure overflow-x-auto text-[0.8125rem] leading-relaxed whitespace-pre-wrap">{markdown}</pre>
        ) : (
          <p className="text-sm text-muted-foreground">No notes for this audience.</p>
        )}
      </div>
    </section>
  );
}
