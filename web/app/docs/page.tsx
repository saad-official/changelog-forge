import type { Metadata } from "next";
import Link from "next/link";
import { CodeBlock } from "@/components/code-block";
import { API_URL } from "@/lib/config";
import { container, links, textLink } from "@/lib/site";
import { actionWorkflow, cliEnv, cliExamples, cliInstall, curlCreate, curlEvents, curlProcess, curlResult } from "@/lib/snippets";
import { cn } from "@/lib/utils";

export const metadata: Metadata = {
  title: "Docs",
  description: "Use Changelog Forge from the CLI, over HTTP, or as a GitHub Action.",
};

const toc = [
  { id: "cli", label: "CLI" },
  { id: "api", label: "HTTP API" },
  { id: "action", label: "GitHub Action" },
];

export default function DocsPage() {
  const api = API_URL;
  return (
    <div className={cn(container, "py-10 sm:py-14")}>
      <div className="grid gap-10 lg:grid-cols-[12rem_minmax(0,1fr)] lg:gap-14">
        <nav aria-label="On this page" className="lg:sticky lg:top-8 lg:h-fit">
          <p className="hunk">@@ docs @@</p>
          <ul className="mt-3 flex gap-5 text-sm lg:flex-col lg:gap-2.5">
            {toc.map((t) => (
              <li key={t.id}>
                <a href={`#${t.id}`} className={textLink}>
                  {t.label}
                </a>
              </li>
            ))}
          </ul>
        </nav>

        <div className="min-w-0 space-y-16">
          <header className="max-w-2xl space-y-3">
            <h1 className="text-4xl font-extrabold [font-stretch:90%] sm:text-5xl">Docs</h1>
            <p className="text-[1.0625rem] leading-relaxed text-foreground/80">
              One engine, three ways in. The{" "}
              <Link href={links.forge} className={textLink}>
                web app
              </Link>{" "}
              is the quickest; the CLI and the Action fit it into a release process. The full reference is in the{" "}
              <a href={links.repo} className={textLink}>
                repository README
              </a>
              .
            </p>
          </header>

          <section id="cli" aria-labelledby="cli-title" className="scroll-mt-8 space-y-5">
            <h2 id="cli-title" className="text-2xl font-extrabold sm:text-3xl">
              CLI
            </h2>
            <p className="max-w-2xl text-foreground/80">
              Prints Markdown to stdout. <code className="figure text-[0.9em]">--json</code> switches to the JSON model and{" "}
              <code className="figure text-[0.9em]">--out</code> writes to a file. Ranges are{" "}
              <code className="figure text-[0.9em]">base..head</code> with tags, branches or SHAs, or a compare URL.
            </p>
            <CodeBlock label="install" code={cliInstall} />
            <CodeBlock label="usage" code={cliExamples} />
            <CodeBlock label="environment" code={cliEnv} />
          </section>

          <section id="api" aria-labelledby="api-title" className="scroll-mt-8 space-y-5">
            <h2 id="api-title" className="text-2xl font-extrabold sm:text-3xl">
              HTTP API
            </h2>
            <p className="max-w-2xl text-foreground/80">
              Create a run, ask the API to process it, then follow its progress as Server-Sent Events or poll the run. No
              key is needed; runs are limited to 10 per hour per address. OpenAPI lives at{" "}
              <a href={`${api}/api/docs`} className={cn(textLink, "figure break-all")}>
                {api}/api/docs
              </a>
              .
            </p>
            <CodeBlock label="1 · create" code={curlCreate(api)} />
            <CodeBlock label="2 · process" code={curlProcess(api)} />
            <CodeBlock label="3 · follow" code={curlEvents(api)} />
            <CodeBlock label="4 · results" code={curlResult(api)} />
            <p className="max-w-2xl text-sm text-muted-foreground">
              Errors come back as JSON with an HTTP status: <span className="figure">429</span> when the hourly limit is
              reached, <span className="figure">422</span> for a range over 400 commits or a malformed request,{" "}
              <span className="figure">404</span> for a repository or ref that does not exist.
            </p>
          </section>

          <section id="action" aria-labelledby="action-title" className="scroll-mt-8 space-y-5">
            <h2 id="action-title" className="text-2xl font-extrabold sm:text-3xl">
              GitHub Action
            </h2>
            <p className="max-w-2xl text-foreground/80">
              On a version tag, the Action works out the previous tag, generates both documents and writes them into the
              release body, or as a comment on a release PR.
            </p>
            <CodeBlock label=".github/workflows/release-notes.yml" code={actionWorkflow} />
          </section>
        </div>
      </div>
    </div>
  );
}
