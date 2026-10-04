import Link from "next/link";
import { ArrowRightIcon } from "lucide-react";
import { CodeBlock } from "@/components/code-block";
import { Faq } from "@/components/marketing/faq";
import { NotesDocument } from "@/components/notes/notes-document";
import { UsageCard } from "@/components/notes/usage-card";
import { VerificationPanel } from "@/components/notes/verification-panel";
import { RunDetailSchema } from "@/lib/api";
import { formatUsd } from "@/lib/format";
import { EXAMPLE_BASE, EXAMPLE_HEAD, EXAMPLE_REPO, exampleDevNotes, exampleRun, exampleUserNotes } from "@/lib/mock";
import { normaliseNotes } from "@/lib/notes";
import { container, ctaPrimary, ctaSecondary, links, textLink } from "@/lib/site";
import { actionWorkflow, cliExamples } from "@/lib/snippets";
import { cn } from "@/lib/utils";

const example = RunDetailSchema.parse(exampleRun);
const userNotes = normaliseNotes(exampleUserNotes, EXAMPLE_REPO);
const devNotes = normaliseNotes(exampleDevNotes, EXAMPLE_REPO);

const STAGES: { name: string; tier: string; tone: string; sentence: string }[] = [
  {
    name: "collect",
    tier: "GitHub REST",
    tone: "text-pencil",
    sentence: "Reads the compare range and the pull request behind each commit, cached by SHA so a re-run only fetches what is new.",
  },
  {
    name: "group",
    tier: "no model",
    tone: "text-pencil",
    sentence: "Folds merge and squash commits into one change per PR, then packs them into groups of about 6,000 tokens without splitting a PR.",
  },
  {
    name: "map",
    tier: "cheap model",
    tone: "text-signal-ink",
    sentence: "A small model reads one group at a time and must answer in a strict schema: category, two summaries, breaking or not, confidence, refs.",
  },
  {
    name: "reduce",
    tier: "capable model",
    tone: "text-signal-ink",
    sentence: "A larger model merges the groups and writes the prose; both audiences share one item list, so the two documents cannot disagree on facts.",
  },
  {
    name: "verify",
    tier: "plain code",
    tone: "text-release-ink",
    sentence: "Every SHA and PR number must exist in the input, and breaking claims under 0.60 confidence are downgraded. No model gets a vote here.",
  },
  {
    name: "render",
    tier: "no model",
    tone: "text-pencil",
    sentence: "GitHub-flavoured Markdown with every item linked to its PR or commit, plus the same data as JSON for your own tooling.",
  },
];

const VERIFY_LINES: { mark: string; tone: string; text: string }[] = [
  { mark: "✓", tone: "text-term-green", text: "#3373  found in input  (fdf7786)" },
  { mark: "✓", tone: "text-term-green", text: "#3366  found in input  (c8d5e34)" },
  { mark: "✗", tone: "text-term-red", text: "#3390  not in v4.5.11..v4.6.0  → dropped" },
  { mark: "↓", tone: "text-term-amber", text: "#3318  breaking 0.45 < 0.60  → possibly breaking (dev only)" },
  { mark: "✓", tone: "text-term-green", text: "41 refs checked · 1 dropped · 1 downgraded" },
];

function SectionHead({ hunk, id, title, children }: { hunk: string; id: string; title: string; children?: React.ReactNode }) {
  return (
    <div className="max-w-2xl space-y-3">
      <p className="hunk" aria-hidden="true">
        @@ {hunk} @@
      </p>
      <h2 id={id} className="text-3xl leading-tight font-extrabold [font-stretch:90%] sm:text-4xl">
        {title}
      </h2>
      {children ? <div className="space-y-3 text-[1.0625rem] leading-relaxed text-foreground/80">{children}</div> : null}
    </div>
  );
}

export default function HomePage() {
  return (
    <>
      {/* Hero */}
      <section aria-labelledby="hero-title" className="border-b border-border">
        <div className={cn(container, "pt-12 pb-14 sm:pt-16 sm:pb-20")}>
          <div className="max-w-3xl">
            <p className="hunk">
              @@ -{EXAMPLE_BASE} +{EXAMPLE_HEAD} @@
            </p>
            <h1 id="hero-title" className="mt-3 text-[2.6rem] leading-[1.02] font-extrabold [font-stretch:86%] sm:text-6xl lg:text-7xl">
              A git range in.
              <br />
              Release notes for <span className="text-release-ink">two audiences</span> out.
            </h1>
            <p className="mt-5 max-w-2xl text-lg leading-relaxed text-foreground/80">
              Point it at a public GitHub repository and two refs. It reads every commit and pull request, writes notes
              your users can read and notes your developers can act on, links every item to its source, and checks every
              reference before you see it.
            </p>
            <div className="mt-8 flex flex-col gap-3 sm:flex-row">
              <Link href={links.forge} className={ctaPrimary}>
                Forge release notes
                <ArrowRightIcon className="size-4" aria-hidden="true" />
              </Link>
              <Link href={links.docs} className={ctaSecondary}>
                CLI, API and Action
              </Link>
            </div>
            <p className="mt-4 text-sm text-muted-foreground">No sign-up. Public repos work as they are.</p>
          </div>

          <div className="mt-12 sm:mt-14">
            <div className="flex flex-col gap-2 rounded-t-lg bg-term px-4 py-3 text-term-fg sm:flex-row sm:items-center sm:justify-between">
              <p className="figure min-w-0 text-[0.8125rem] break-words">
                <span className="text-term-dim" aria-hidden="true">
                  ${" "}
                </span>
                changelog-forge {EXAMPLE_REPO} {EXAMPLE_BASE}..{EXAMPLE_HEAD} --audience user,dev
              </p>
              <p className="figure shrink-0 text-xs text-term-dim">
                {example.commit_count} commits · {example.group_count} groups · {formatUsd(example.usage.usd)}
              </p>
            </div>
            <div className="ruled grid gap-4 rounded-b-lg border border-t-0 border-border bg-muted/40 p-3 sm:p-4 lg:grid-cols-2">
              <h2 className="sr-only">
                Example output for {EXAMPLE_REPO} {EXAMPLE_BASE}..{EXAMPLE_HEAD}
              </h2>
              {(["user", "dev"] as const).map((audience) => (
                <div
                  key={audience}
                  className="max-h-[28rem] min-w-0 overflow-y-auto rounded-lg sm:max-h-[36rem]"
                  tabIndex={0}
                  role="region"
                  aria-label={`Example ${audience === "user" ? "user" : "developer"} notes, scrollable`}
                >
                  <NotesDocument idPrefix="hero" audience={audience} notes={audience === "user" ? userNotes : devNotes} level={3} />
                </div>
              ))}
            </div>
            <p className="mt-3 text-sm text-muted-foreground">
              A real range of <a className={textLink} href={`https://github.com/${EXAMPLE_REPO}/compare/${EXAMPLE_BASE}...${EXAMPLE_HEAD}`}>{EXAMPLE_REPO}</a>: the PRs and SHAs are real; the prose is a sample of the output.
            </p>
          </div>
        </div>
      </section>

      {/* How it works */}
      <section id="how-it-works" aria-labelledby="how-title" className="scroll-mt-6 border-b border-border">
        <div className={cn(container, "py-16 sm:py-20")}>
          <SectionHead hunk="how it works" id="how-title" title="Six stages. Two of them call a model.">
            <p>
              Long ranges do not fit one prompt, and one prompt would be the expensive kind. So the work is split: a cheap
              model on many small pieces, a better model once on the merged result, and plain code wherever code is enough.
            </p>
          </SectionHead>
          <ol className="mt-10 grid gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-2 lg:grid-cols-3">
            {STAGES.map((s, i) => (
              <li key={s.name} className="flex flex-col gap-3 bg-sheet p-5 sm:p-6">
                <div className="flex items-baseline justify-between gap-3">
                  <h3 className="figure text-lg font-semibold tracking-normal">
                    <span className="mr-2 text-muted-foreground">{String(i + 1).padStart(2, "0")}</span>
                    {s.name}
                    {i < STAGES.length - 1 ? (
                      <span className="ml-2 text-muted-foreground" aria-hidden="true">
                        →
                      </span>
                    ) : null}
                  </h3>
                  <span className={cn("figure text-xs", s.tone)}>{s.tier}</span>
                </div>
                <p className="text-[0.9375rem] leading-relaxed text-foreground/80">{s.sentence}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* Verification */}
      <section id="verification" aria-labelledby="verify-section-title" className="scroll-mt-6 border-b border-border">
        <div className={cn(container, "grid gap-10 py-16 sm:py-20 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:gap-14")}>
          <div className="min-w-0 space-y-8">
            <SectionHead hunk="verify" id="verify-section-title" title="Every PR number is checked against the input.">
              <p>
                Models write plausible references. Plausible is not good enough for a changelog people will click. After the
                models are done, a deterministic verifier compares every SHA and PR number with what was actually collected.
              </p>
              <p>
                Invented ones are dropped <em>and shown</em>, so you can see what the model tried. Breaking-change claims
                below 0.60 confidence become &ldquo;possibly breaking&rdquo; in the developer notes and stay out of the user
                notes.
              </p>
            </SectionHead>
            <div className="overflow-hidden rounded-lg bg-term text-term-fg">
              <p className="figure border-b border-term-rule px-4 py-2 text-xs text-term-dim">verify · {EXAMPLE_REPO}</p>
              <ul className="figure space-y-0.5 overflow-x-auto px-4 py-3 text-[0.8125rem] leading-relaxed">
                {VERIFY_LINES.map((l) => (
                  <li key={l.text} className={cn("whitespace-pre-wrap", l.tone)}>
                    <span aria-hidden="true">{l.mark} </span>
                    {l.text}
                  </li>
                ))}
              </ul>
            </div>
          </div>
          <VerificationPanel
            verified={example.verified}
            repo={EXAMPLE_REPO}
            commitCount={example.commit_count}
            level={3}
            className="h-fit lg:mt-14"
          />
        </div>
      </section>

      {/* Cost */}
      <section id="cost" aria-labelledby="cost-title" className="border-b border-border">
        <div className={cn(container, "grid gap-10 py-16 sm:py-20 lg:grid-cols-[minmax(0,1fr)_24rem] lg:gap-14")}>
          <SectionHead hunk="cost" id="cost-title" title="Every run shows tokens and dollars at paid rates.">
            <p>
              The demo runs on free tiers, which would hide the real price. So every model call goes through a ledger that
              prices it at the provider&rsquo;s paid rate, and the run page shows the total, the split by model and the cost
              per 100 commits.
            </p>
            <p>
              Each run also has a ceiling of <span className="figure">$0.05</span>. The target is under{" "}
              <span className="figure">$0.01</span> per 100 commits.
            </p>
          </SectionHead>
          <UsageCard usage={example.usage} commitCount={example.commit_count} level={3} className="h-fit" />
        </div>
      </section>

      {/* CLI and Action */}
      <section aria-labelledby="tools-title" className="border-b border-border">
        <div className={cn(container, "py-16 sm:py-20")}>
          <SectionHead hunk="cli + action" id="tools-title" title="Same engine in your terminal and in CI.">
            <p>
              The web app, the CLI and the GitHub Action all call the same pipeline. Tag a release and the Action writes the
              notes into the release body or a PR comment.{" "}
              <Link href={links.docs} className={textLink}>
                Full usage in the docs
              </Link>
              .
            </p>
          </SectionHead>
          <div className="mt-10 grid gap-5 lg:grid-cols-2">
            <CodeBlock label="terminal" code={cliExamples} />
            <CodeBlock label=".github/workflows/release-notes.yml" code={actionWorkflow} />
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section aria-labelledby="faq-title" className="border-b border-border">
        <div className={cn(container, "grid gap-10 py-16 sm:py-20 lg:grid-cols-[18rem_minmax(0,1fr)] lg:gap-14")}>
          <SectionHead hunk="faq" id="faq-title" title="Questions" />
          <Faq />
        </div>
      </section>

      {/* Closing CTA */}
      <section aria-labelledby="cta-title">
        <div className={cn(container, "flex flex-col items-start gap-6 py-16 sm:flex-row sm:items-center sm:justify-between sm:py-20")}>
          <div>
            <h2 id="cta-title" className="text-3xl font-extrabold [font-stretch:90%] sm:text-4xl">
              Your last release, written up properly.
            </h2>
            <p className="mt-2 text-foreground/75">Paste the repo and two tags, then watch every step of the run as it happens.</p>
          </div>
          <Link href={links.forge} className={cn(ctaPrimary, "shrink-0")}>
            Forge release notes
            <ArrowRightIcon className="size-4" aria-hidden="true" />
          </Link>
        </div>
      </section>
    </>
  );
}
