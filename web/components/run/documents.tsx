"use client";

import { useCallback, useState, useSyncExternalStore } from "react";
import { BracesIcon, DownloadIcon } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { CopyButton } from "@/components/copy-button";
import { NotesDocument, AUDIENCE_META } from "@/components/notes/notes-document";
import { markdownUrl, type Audience, type RunDetail } from "@/lib/api";
import { API_MOCK } from "@/lib/config";
import { downloadText } from "@/lib/clipboard";
import { normaliseNotes, notesToMarkdown } from "@/lib/notes";

const LG = "(min-width: 64rem)";

function subscribe(cb: () => void) {
  const mql = window.matchMedia(LG);
  mql.addEventListener("change", cb);
  return () => mql.removeEventListener("change", cb);
}

/** Side by side from `lg`, tabs below it. Server snapshot is "wide"; documents only render client-side anyway. */
function useWide() {
  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(LG).matches,
    () => true,
  );
}

function slug(s: string) {
  return s.replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "");
}

const actionClass =
  "inline-flex h-8 items-center gap-1.5 rounded-md border border-input bg-sheet px-2.5 text-xs font-semibold text-foreground hover:bg-muted motion-safe:transition-colors";

export function Documents({ run }: { run: RunDetail }) {
  const wide = useWide();
  const [manual, setManual] = useState<{ audience: Audience; text: string } | null>(null);
  const selectAll = useCallback((el: HTMLTextAreaElement | null) => {
    el?.focus();
    el?.select();
  }, []);

  const docs = (["user", "dev"] as const).flatMap((audience) => {
    const out = run.outputs[audience];
    if (!out) return [];
    const notes = normaliseNotes(out.json, run.repo);
    const markdown = out.markdown || (notes ? notesToMarkdown(notes) : "");
    return [{ audience, notes, markdown, json: out.json }];
  });

  if (docs.length === 0) {
    return <p className="rounded-lg border border-dashed border-border p-6 text-sm text-muted-foreground">The run finished without documents.</p>;
  }

  const fileBase = `${slug(run.repo.replace("/", "-"))}-${slug(run.base)}..${slug(run.head)}`;

  const render = (d: (typeof docs)[number], idPrefix: string) => (
    <NotesDocument
      key={d.audience}
      idPrefix={idPrefix}
      audience={d.audience}
      notes={d.notes}
      markdown={d.markdown}
      level={2}
      className="h-full"
      actions={
        <>
          <CopyButton
            text={d.markdown}
            label="Copy Markdown"
            srLabel={`, ${AUDIENCE_META[d.audience].title.toLowerCase()}`}
            onFallback={() => setManual({ audience: d.audience, text: d.markdown })}
          />
          <a
            className={actionClass}
            href={API_MOCK ? `data:text/markdown;charset=utf-8,${encodeURIComponent(d.markdown)}` : markdownUrl(run.id, d.audience)}
            download={`${fileBase}-${d.audience}.md`}
          >
            <DownloadIcon className="size-3.5" aria-hidden="true" />
            .md
            <span className="sr-only"> download, {AUDIENCE_META[d.audience].title.toLowerCase()}</span>
          </a>
          <button
            type="button"
            className={actionClass}
            onClick={() => downloadText(`${fileBase}-${d.audience}.json`, JSON.stringify(d.json ?? null, null, 2))}
          >
            <BracesIcon className="size-3.5" aria-hidden="true" />
            JSON
            <span className="sr-only"> download, {AUDIENCE_META[d.audience].title.toLowerCase()}</span>
          </button>
        </>
      }
    />
  );

  return (
    <div className="space-y-4">
      {manual ? (
        <div className="space-y-2 rounded-lg border border-signal/50 bg-signal-wash p-4">
          <label htmlFor="manual-copy" className="block text-sm font-semibold text-signal-ink">
            Copy the {AUDIENCE_META[manual.audience].title.toLowerCase()} Markdown by hand (it is selected)
          </label>
          <textarea
            id="manual-copy"
            ref={selectAll}
            readOnly
            value={manual.text}
            rows={8}
            className="figure w-full rounded-md border border-input bg-sheet p-3 text-xs"
          />
          <button type="button" className={actionClass} onClick={() => setManual(null)}>
            Done
          </button>
        </div>
      ) : null}

      {docs.length === 1 ? (
        <div className="mx-auto max-w-3xl">{render(docs[0], "doc")}</div>
      ) : wide ? (
        <div className="grid grid-cols-2 items-start gap-5">{docs.map((d) => render(d, "doc"))}</div>
      ) : (
        <Tabs defaultValue={docs[0].audience} className="gap-3">
          <TabsList className="h-10 w-full">
            {docs.map((d) => (
              <TabsTrigger key={d.audience} value={d.audience} className="h-full">
                {AUDIENCE_META[d.audience].title}
              </TabsTrigger>
            ))}
          </TabsList>
          {docs.map((d) => (
            <TabsContent key={d.audience} value={d.audience}>
              {render(d, "tab")}
            </TabsContent>
          ))}
        </Tabs>
      )}
    </div>
  );
}
