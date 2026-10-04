import { describe, expect, it } from "vitest";
import { formatElapsed, formatUsd, parseRepoInput, refError, usdPer100Commits } from "@/lib/format";
import { normaliseBaseUrl } from "@/lib/config";

describe("parseRepoInput", () => {
  it("accepts owner/name", () => {
    expect(parseRepoInput("vercel/next.js")).toEqual({ repo: "vercel/next.js", fromUrl: false });
  });

  it("reads base and head from a compare URL (three dots, slashes in refs, query string)", () => {
    expect(parseRepoInput("https://github.com/honojs/hono/compare/v4.5.11...v4.6.0")).toMatchObject({
      repo: "honojs/hono",
      base: "v4.5.11",
      head: "v4.6.0",
      fromUrl: true,
    });
    expect(parseRepoInput("github.com/o/r/compare/main...feature/new-thing?expand=1")).toMatchObject({
      repo: "o/r",
      base: "main",
      head: "feature/new-thing",
    });
  });

  it("accepts a two-dot compare URL and a repo URL with .git", () => {
    expect(parseRepoInput("https://github.com/o/r/compare/a1b2c3d..e4f5a6b")).toMatchObject({ base: "a1b2c3d", head: "e4f5a6b" });
    expect(parseRepoInput("https://github.com/o/r.git")).toMatchObject({ repo: "o/r", fromUrl: true });
  });

  it("accepts owner/name@base..head", () => {
    expect(parseRepoInput("o/r@v1..v2")).toMatchObject({ repo: "o/r", base: "v1", head: "v2" });
  });

  it("rejects junk with a message", () => {
    expect(parseRepoInput("").error).toBeTruthy();
    expect(parseRepoInput("not a repo").error).toBeTruthy();
    expect(parseRepoInput("https://github.com/o/r/compare/v1").error).toMatch(/both refs/);
  });
});

describe("refError", () => {
  it("allows tags, branches with slashes and SHAs", () => {
    expect(refError("v1.2.0", "base")).toBeUndefined();
    expect(refError("release/2026-10", "head")).toBeUndefined();
    expect(refError("73ff6c0", "head")).toBeUndefined();
  });
  it("rejects empty refs, spaces and ranges", () => {
    expect(refError(" ", "base")).toMatch(/Enter/);
    expect(refError("v1 2", "base")).toMatch(/spaces/);
    expect(refError("v1..v2", "head")).toMatch(/one ref/);
  });
});

describe("number formatting", () => {
  it("prints dollars at LLM precision", () => {
    expect(formatUsd(0)).toBe("$0.00");
    expect(formatUsd(0.00004)).toBe("<$0.0001");
    expect(formatUsd(0.003713)).toBe("$0.0037");
    expect(formatUsd(0.0421)).toBe("$0.042");
    expect(formatUsd(1.2)).toBe("$1.20");
  });
  it("prints elapsed like a build log", () => {
    expect(formatElapsed(0)).toBe("00:00.0");
    expect(formatElapsed(8650)).toBe("00:08.6");
    expect(formatElapsed(61_200)).toBe("01:01.2");
  });
  it("computes cost per 100 commits", () => {
    expect(usdPer100Commits(0.002, 20)).toBeCloseTo(0.01);
    expect(usdPer100Commits(0.002, 0)).toBeUndefined();
  });
});

describe("normaliseBaseUrl", () => {
  it("defaults to the local API and strips trailing slashes", () => {
    expect(normaliseBaseUrl(undefined)).toBe("http://localhost:7860");
    expect(normaliseBaseUrl("  ")).toBe("http://localhost:7860");
    expect(normaliseBaseUrl("https://changelog-forge-api.vercel.app/")).toBe("https://changelog-forge-api.vercel.app");
  });
});
