import { describe, expect, it } from "vitest";
import { countItems, normaliseNotes, notesToMarkdown, toCategory, toRef } from "@/lib/notes";
import { EXAMPLE_REPO, exampleDevNotes, exampleUserNotes } from "@/lib/mock";

const repo = "o/r";

describe("toRef", () => {
  it("reads PR numbers in every shape", () => {
    for (const raw of ["#123", "123", 123, "PR #123", { kind: "pr", id: "123" }, { number: 123 }, "https://github.com/o/r/pull/123"]) {
      const r = toRef(raw, repo);
      expect(r, JSON.stringify(raw)).toMatchObject({ kind: "pr", id: "123", label: "#123" });
    }
    expect(toRef("#123", repo)?.url).toBe("https://github.com/o/r/pull/123");
  });

  it("reads SHAs and shortens the label", () => {
    const r = toRef("73FF6C0E82D66468E28ED439481220F56AB03882", repo);
    expect(r).toMatchObject({ kind: "commit", label: "73ff6c0" });
    expect(r?.url).toBe("https://github.com/o/r/commit/73ff6c0e82d66468e28ed439481220f56ab03882");
    expect(toRef({ kind: "commit", sha: "abc1234" }, repo)?.label).toBe("abc1234");
  });

  it("keeps a given https URL but never a javascript: one", () => {
    expect(toRef({ kind: "pr", id: "5", url: "https://example.com/p/5" }, repo)?.url).toBe("https://example.com/p/5");
    expect(toRef({ kind: "pr", id: "5", url: "javascript:alert(1)" }, repo)?.url).toBe("https://github.com/o/r/pull/5");
    expect(toRef("javascript:alert(1)", repo)).toBeNull();
  });

  it("returns null for junk", () => {
    expect(toRef("not a ref", repo)).toBeNull();
    expect(toRef(null, repo)).toBeNull();
    expect(toRef({ kind: "pr", id: "abc" }, repo)).toBeNull();
  });
});

describe("toCategory", () => {
  it("maps common spellings", () => {
    expect(toCategory("Breaking changes")).toBe("breaking");
    expect(toCategory("feat")).toBe("features");
    expect(toCategory("Bug fixes")).toBe("fixes");
    expect(toCategory("perf")).toBe("performance");
    expect(toCategory("Documentation")).toBe("docs");
    expect(toCategory("chore")).toBe("internal");
  });
});

describe("normaliseNotes", () => {
  it("orders sections breaking-first and keeps refs PR-first, deduplicated", () => {
    const notes = normaliseNotes(
      {
        intro: "Hi",
        sections: [
          { category: "fixes", items: [{ summary: "A fix", refs: ["abc1234", "#2", "#2"] }] },
          { category: "breaking", items: [{ summary: "Removed X", refs: ["#1"], migration_note: "Use Y" }] },
        ],
      },
      repo,
    )!;
    expect(notes.sections.map((s) => s.category)).toEqual(["breaking", "fixes"]);
    expect(notes.sections[0].items[0]).toMatchObject({ breaking: true, migration: "Use Y" });
    expect(notes.sections[1].items[0].refs.map((r) => r.label)).toEqual(["#2", "abc1234"]);
  });

  it("groups a flat item list and honours possibly_breaking", () => {
    const notes = normaliseNotes(
      {
        items: [
          { summary: "New thing", category: "feature", refs: [{ kind: "pr", id: "9" }] },
          { summary: "Maybe breaks", category: "breaking", possibly_breaking: true, breaking_confidence: 0.4, refs: ["#8"] },
        ],
      },
      repo,
    )!;
    expect(countItems(notes)).toBe(2);
    const maybe = notes.sections.flatMap((s) => s.items).find((i) => i.summary === "Maybe breaks")!;
    expect(maybe).toMatchObject({ breaking: false, possiblyBreaking: true, confidence: 0.4 });
    expect(maybe.category).not.toBe("breaking");
  });

  it("parses a JSON string and returns null for nothing usable", () => {
    expect(normaliseNotes(JSON.stringify({ intro: "x" }), repo)?.intro).toBe("x");
    expect(normaliseNotes(null, repo)).toBeNull();
    expect(normaliseNotes({ sections: [] }, repo)).toBeNull();
    expect(normaliseNotes("{not json", repo)).toBeNull();
  });

  it("renders Markdown with links in GitHub form", () => {
    const md = notesToMarkdown(normaliseNotes(exampleDevNotes, EXAMPLE_REPO)!);
    expect(md).toContain("## Features");
    expect(md).toContain("[#3373](https://github.com/honojs/hono/pull/3373)");
    expect(md).toContain("[fdf7786](https://github.com/honojs/hono/commit/fdf77862acbbfc1540ff0732a4cfd74a55781393)");
    expect(md).toContain("_(possibly breaking)_");
    expect(md).toMatch(/Migration: /);
  });

  it("keeps the user fixture free of possibly-breaking items (the verifier rule)", () => {
    const notes = normaliseNotes(exampleUserNotes, EXAMPLE_REPO)!;
    expect(notes.sections.flatMap((s) => s.items).some((i) => i.possiblyBreaking || i.breaking)).toBe(false);
  });
});
