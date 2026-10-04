import { links, textLink } from "@/lib/site";

const items: { q: string; a: React.ReactNode }[] = [
  {
    q: "Does it work on private repositories?",
    a: (
      <p>
        Yes, if you paste a GitHub token that can read the repository. The token is sent with that one run and never
        stored. There is no GitHub sign-in in this version, and no accounts at all.
      </p>
    ),
  },
  {
    q: "What stops it from inventing changes?",
    a: (
      <p>
        The verifier. After the models finish, plain code checks every SHA and PR number against the commits that were
        actually collected. Anything that does not match is removed from both documents and listed on the run page, and
        every remaining item must keep at least one working link.
      </p>
    ),
  },
  {
    q: "Which models does it use?",
    a: (
      <p>
        A routing table decides. Today the per-group step runs on a small open-weight model on Groq and the merge step on a
        larger one, with Gemini as a fallback. Prompts are versioned files and each run records which versions it used.
      </p>
    ),
  },
  {
    q: "How big a range can it take?",
    a: (
      <p>
        Up to 400 commits per run. A larger range is refused with a clear message before any model is called, so it costs
        nothing. Narrow it to one release at a time.
      </p>
    ),
  },
  {
    q: "Why two documents instead of one?",
    a: (
      <p>
        Users want to know what changed for them; developers need breaking changes, migration steps and every PR. Both
        documents are written from one merged list of items, so they never disagree about what happened.
      </p>
    ),
  },
  {
    q: "What is kept, and for how long?",
    a: (
      <p>
        Runs, their progress logs and their outputs are kept for 30 days, then purged. Commit and PR data from public
        repositories is cached by SHA so repeat runs are cheaper. Tokens are never kept.
      </p>
    ),
  },
  {
    q: "Who made this?",
    a: (
      <p>
        It is the first project of the{" "}
        <a href={links.journey} className={textLink}>
          AI Engineering Journey
        </a>{" "}
        and app 7 of the{" "}
        <a href={links.series} className={textLink}>
          Vibe Build Series
        </a>
        . The{" "}
        <a href={links.repo} className={textLink}>
          source
        </a>{" "}
        includes the evaluation set and its latest scores.
      </p>
    ),
  },
];

/** Native disclosure list: works without JavaScript and with find-in-page. */
export function Faq() {
  return (
    <div className="min-w-0 border-t border-border">
      {items.map((item) => (
        <details key={item.q} className="group border-b border-border">
          <summary className="flex cursor-pointer list-none items-start justify-between gap-6 py-5 [&::-webkit-details-marker]:hidden">
            <h3 className="text-lg leading-snug font-semibold sm:text-xl">{item.q}</h3>
            <span
              aria-hidden="true"
              className="figure mt-0.5 grid size-7 shrink-0 place-items-center rounded-sm border border-border text-base leading-none group-open:border-foreground group-open:bg-foreground group-open:text-background"
            >
              <span className="group-open:hidden">+</span>
              <span className="hidden group-open:inline">&minus;</span>
            </span>
          </summary>
          <div className="max-w-2xl space-y-3 pb-6 text-[0.9375rem] leading-relaxed text-foreground/85">{item.a}</div>
        </details>
      ))}
    </div>
  );
}
