import { eventStatus, isTerminal, type RunEvent, type RunStatus } from "./api";

export const STAGES = ["collect", "group", "map", "reduce", "verify", "render"] as const;
export type Stage = (typeof STAGES)[number];

/** Index of the stage a status means is in progress (6 = all done, -1 = not started). */
const STATUS_STAGE: Record<RunStatus, number> = {
  queued: -1,
  collecting: 0,
  mapping: 2,
  reducing: 3,
  verifying: 4,
  done: 6,
  failed: -1,
};

const KIND_STAGE: Record<string, number> = {
  collect: 0,
  group: 1,
  chunk: 1,
  normalise: 1,
  map: 2,
  reduce: 3,
  verify: 4,
  render: 5,
};

export type Progress = {
  status: RunStatus;
  /** Stage currently running (0-5), 6 when done, -1 before collecting starts. */
  stage: number;
  /** Stage that was running when the run failed. */
  failedStage?: number;
  /** "drafting group k of m" from map events. */
  mapGroup?: { k: number; m: number };
  commitCount?: number;
  groupCount?: number;
};

function positiveInt(v: unknown): number | undefined {
  const n = typeof v === "string" ? Number(v) : v;
  return typeof n === "number" && Number.isFinite(n) && n > 0 ? Math.round(n) : undefined;
}

/** Fold the event stream (plus the last known run status) into what the stage track shows. */
export function deriveProgress(events: RunEvent[], runStatus: RunStatus | undefined): Progress {
  let status: RunStatus = runStatus ?? "queued";
  let stage = STATUS_STAGE[status];
  let mapGroup: Progress["mapGroup"];
  let commitCount: number | undefined;
  let groupCount: number | undefined;
  let failed = status === "failed";

  for (const e of events) {
    const s = eventStatus(e);
    if (s) {
      if (s === "failed") failed = true;
      else stage = Math.max(stage, STATUS_STAGE[s]);
      // Events never move a terminal run backwards.
      if (!isTerminal(status)) status = s;
    }
    const k = KIND_STAGE[e.kind];
    if (k !== undefined) stage = Math.max(stage, k);
    const d = e.data;
    commitCount = positiveInt(d.commit_count) ?? commitCount;
    groupCount = positiveInt(d.group_count) ?? positiveInt(d.groups) ?? groupCount;
    const gk = positiveInt(d.group) ?? positiveInt(d.k);
    const gm = positiveInt(d.groups) ?? positiveInt(d.group_count) ?? positiveInt(d.m);
    if (e.kind === "map" && gk && gm) mapGroup = { k: gk, m: gm };
  }

  if (status === "done") stage = 6;
  if (failed) {
    status = "failed";
    return { status, stage, failedStage: Math.max(0, stage), mapGroup, commitCount, groupCount };
  }
  return { status, stage, mapGroup, commitCount, groupCount };
}

/** Insert an event by seq, ignoring duplicates (SSE replays on reconnect). */
export function mergeEvent(list: RunEvent[], e: RunEvent): RunEvent[] {
  if (list.some((x) => x.seq === e.seq)) return list;
  const next = [...list, e];
  if (list.length > 0 && list[list.length - 1].seq > e.seq) next.sort((a, b) => a.seq - b.seq);
  return next;
}

export type LineTone = "dim" | "plain" | "ok" | "warn" | "error";

/** Colour for a log line, from data.level first, then the kind and wording. */
export function lineTone(e: RunEvent): LineTone {
  const level = String(e.data.level ?? "").toLowerCase();
  if (level === "error" || e.kind === "failed") return "error";
  if (level === "warn" || level === "warning") return /dropp/i.test(e.message) ? "error" : "warn";
  if (e.kind === "done") return "ok";
  if (e.kind === "status" || e.kind === "collect" || e.kind === "group" || e.kind === "chunk") return "dim";
  return "plain";
}
