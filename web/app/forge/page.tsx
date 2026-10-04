import type { Metadata } from "next";
import { ForgeForm } from "@/components/forge/forge-form";
import { container } from "@/lib/site";

export const metadata: Metadata = {
  title: "Forge release notes",
  description: "Paste a public GitHub repo and a range; get release notes for users and developers.",
};

function first(v: string | string[] | undefined): string {
  return (Array.isArray(v) ? v[0] : v) ?? "";
}

export default async function ForgePage({ searchParams }: PageProps<"/forge">) {
  const sp = await searchParams;
  const audiences = first(sp.audiences)
    .split(",")
    .filter((a): a is "user" | "dev" => a === "user" || a === "dev");

  return (
    <div className={`${container} py-10 sm:py-14`}>
      <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_20rem] lg:gap-14">
        <div className="min-w-0">
          <p className="hunk">@@ new run @@</p>
          <h1 className="mt-2 text-4xl font-extrabold [font-stretch:90%] sm:text-5xl">Forge release notes</h1>
          <p className="mt-3 max-w-xl text-muted-foreground">
            A public repository and two refs. The run collects up to 400 commits, drafts both documents and checks every
            reference before you see it.
          </p>
          <ForgeForm
            initial={{
              repo: first(sp.repo),
              base: first(sp.base),
              head: first(sp.head),
              audiences: audiences.length > 0 ? audiences : ["user", "dev"],
            }}
          />
        </div>
        <aside aria-labelledby="limits-title" className="h-fit space-y-4 rounded-lg border border-border bg-sheet p-5 text-sm">
          <h2 id="limits-title" className="text-base font-bold">
            Limits, plainly
          </h2>
          <dl className="space-y-3">
            <div>
              <dt className="font-semibold">Commits per run</dt>
              <dd className="text-muted-foreground">
                Up to <span className="figure text-foreground">400</span>. Bigger ranges are refused before any model runs.
              </dd>
            </div>
            <div>
              <dt className="font-semibold">Runs per hour</dt>
              <dd className="text-muted-foreground">
                <span className="figure text-foreground">10</span> per address. There are no accounts.
              </dd>
            </div>
            <div>
              <dt className="font-semibold">Cost ceiling</dt>
              <dd className="text-muted-foreground">
                Each run stops at <span className="figure text-foreground">$0.05</span> of model spend, priced at paid rates.
              </dd>
            </div>
            <div>
              <dt className="font-semibold">Private repos</dt>
              <dd className="text-muted-foreground">
                Paste a token with read access. It is used for this run only and never stored.
              </dd>
            </div>
          </dl>
        </aside>
      </div>
    </div>
  );
}
