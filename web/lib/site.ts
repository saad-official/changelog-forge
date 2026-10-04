import { JOURNEY_URL, REPO_URL, SERIES_URL } from "./snippets";

export const links = {
  repo: REPO_URL,
  journey: JOURNEY_URL,
  series: SERIES_URL,
  forge: "/forge",
  docs: "/docs",
  howItWorks: "/#how-it-works",
  verification: "/#verification",
} as const;

/** Page container: 16px gutter on phones. */
export const container = "mx-auto w-full max-w-6xl px-4 sm:px-6 lg:px-8";

/** Inline text link: underlined, darker on hover. Focus comes from the global a:focus-visible rule. */
export const textLink =
  "underline decoration-foreground/30 decoration-1 underline-offset-4 hover:decoration-foreground motion-safe:transition-colors";

/** Primary call to action: graphite slab on paper. */
export const ctaPrimary =
  "inline-flex h-11 items-center justify-center gap-2 rounded-md bg-primary px-5 text-[0.9375rem] font-semibold text-primary-foreground hover:bg-primary/88 motion-safe:transition-colors";

export const ctaSecondary =
  "inline-flex h-11 items-center justify-center gap-2 rounded-md border border-input bg-sheet px-5 text-[0.9375rem] font-semibold text-foreground hover:bg-muted motion-safe:transition-colors";
