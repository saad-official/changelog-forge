import { describe, expect, it } from "vitest";
import { RunDetailSchema, eventStatus, parseRunEvent, type RunEvent } from "@/lib/api";
import { exampleRun } from "@/lib/mock";
import { deriveProgress, lineTone, mergeEvent } from "@/lib/progress";

const mk = (seq: number, kind: string, data: Record<string, unknown> = {}, message = ""): RunEvent => ({ seq, kind, message, data, at: undefined });

describe("RunDetailSchema", () => {
  it("parses the fixture run", () => {
    const r = RunDetailSchema.parse(exampleRun);
    expect(r.status).toBe("done");
    expect(r.usage.total_tokens).toBe(15358 + 4516);
    expect(r.usage.by_model).toHaveLength(2);
    expect(r.verified.dropped_refs).toEqual(["#3390"]);
    expect(r.verified.downgraded[0].confidence).toBe(0.45);
    expect(r.audiences).toEqual(["user", "dev"]);
  });

  it("tolerates a minimal in-progress payload", () => {
    const r = RunDetailSchema.parse({ id: 42, status: "mapping", repo: "o/r", base: "a", head: "b" });
    expect(r).toMatchObject({ id: "42", status: "mapping", commit_count: 0, group_count: 0, outputs: {} });
    expect(r.usage.usd).toBe(0);
    expect(r.verified).toEqual({ dropped_refs: [], downgraded: [], checked_refs: undefined });
    expect(r.error).toBeUndefined();
  });

  it("tolerates nulls, wrong types and unknown statuses", () => {
    const r = RunDetailSchema.parse({
      id: "x",
      status: "teleporting",
      repo: "o/r",
      base: "a",
      head: "b",
      commit_count: null,
      usage: { prompt_tokens: "lots", usd: 0.01, by_model: { "m-1": { prompt_tokens: 5, usd: 0.01 } } },
      outputs: { user: { markdown: null, json: { intro: "x" } }, dev: null },
      verified: { dropped_refs: [7, "#8"], downgraded: ["just a string"] },
      error: null,
    });
    expect(r.status).toBe("queued");
    expect(r.usage.prompt_tokens).toBe(0);
    expect(r.usage.by_model[0]).toMatchObject({ model: "m-1", prompt_tokens: 5 });
    expect(r.outputs.user?.markdown).toBe("");
    expect(r.outputs.dev).toBeUndefined();
    expect(r.verified.dropped_refs).toEqual(["#7", "#8"]);
    expect(r.verified.downgraded[0].summary).toBe("just a string");
  });

  it("falls back to per-audience verification when the run-level one is missing", () => {
    const r = RunDetailSchema.parse({
      id: "x",
      status: "done",
      repo: "o/r",
      base: "a",
      head: "b",
      outputs: {
        user: { markdown: "u", verified: { dropped_refs: ["#1"], downgraded: [] } },
        dev: { markdown: "d", verified: { dropped_refs: ["#1", "#2"], downgraded: [{ summary: "s", breaking_confidence: 0.3 }] } },
      },
    });
    expect(r.verified.dropped_refs).toEqual(["#1", "#2"]);
    expect(r.verified.downgraded).toHaveLength(1);
  });
});

describe("events", () => {
  it("parses SSE payloads and ignores keep-alives and junk", () => {
    const raw = JSON.stringify({ seq: 3, at: "2026-10-04T09:00:00Z", kind: "map", message: "drafting group 1 of 2", data: { group: 1, groups: 2 } });
    expect(parseRunEvent(raw)).toMatchObject({ seq: 3, kind: "map", data: { group: 1, groups: 2 } });
    expect(parseRunEvent("")).toBeNull();
    expect(parseRunEvent("not json")).toBeNull();
    expect(parseRunEvent("[1,2]")).toBeNull();
    expect(parseRunEvent(JSON.stringify({ kind: "log", message: "x" }), 9)?.seq).toBe(9);
    expect(parseRunEvent(JSON.stringify({ seq: 1, kind: "map", message: "m", data: null }))?.data).toEqual({});
  });

  it("derives status from data.status or the done/failed kinds", () => {
    expect(eventStatus(mk(1, "collect", { status: "collecting" }))).toBe("collecting");
    expect(eventStatus(mk(1, "done"))).toBe("done");
    expect(eventStatus(mk(1, "failed"))).toBe("failed");
    expect(eventStatus(mk(1, "map", { status: "bogus" }))).toBeUndefined();
  });

  it("merges by seq without duplicates and keeps order", () => {
    let list = mergeEvent([], mk(1, "log"));
    list = mergeEvent(list, mk(3, "log"));
    list = mergeEvent(list, mk(2, "log"));
    list = mergeEvent(list, mk(3, "log"));
    expect(list.map((e) => e.seq)).toEqual([1, 2, 3]);
  });
});

describe("deriveProgress", () => {
  it("tracks stage, counts and the map group", () => {
    const p = deriveProgress(
      [
        mk(1, "status", { status: "queued" }),
        mk(2, "collect", { status: "collecting" }),
        mk(3, "collect", { commit_count: 17 }),
        mk(4, "group", { group_count: 2, status: "mapping" }),
        mk(5, "map", { group: 2, groups: 2 }),
      ],
      "collecting",
    );
    expect(p).toMatchObject({ status: "mapping", stage: 2, commitCount: 17, groupCount: 2, mapGroup: { k: 2, m: 2 } });
  });

  it("marks the stage that failed", () => {
    const p = deriveProgress([mk(1, "collect", { status: "collecting" }), mk(2, "map", { status: "mapping" }), mk(3, "failed")], "mapping");
    expect(p.status).toBe("failed");
    expect(p.failedStage).toBe(2);
  });

  it("never moves a finished run backwards", () => {
    expect(deriveProgress([mk(1, "collect", { status: "collecting" })], "done")).toMatchObject({ status: "done", stage: 6 });
  });

  it("colours log lines", () => {
    expect(lineTone(mk(1, "done"))).toBe("ok");
    expect(lineTone(mk(1, "verify", { level: "warn" }, "dropped #9: not in range"))).toBe("error");
    expect(lineTone(mk(1, "verify", { level: "warn" }, "downgraded #3"))).toBe("warn");
    expect(lineTone(mk(1, "collect"))).toBe("dim");
    expect(lineTone(mk(1, "map"))).toBe("plain");
  });
});
