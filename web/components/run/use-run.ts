"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  eventStatus,
  getRun,
  isRetryableProcessError,
  isTerminal,
  processingPromise,
  startProcessing,
  subscribeToRun,
  type ProcessOutcome,
  type RunDetail,
  type RunEvent,
} from "@/lib/api";
import { ApiError } from "@/lib/errors";
import { mergeEvent } from "@/lib/progress";

export type Connection = "connecting" | "live" | "polling" | "closed";
export type ProcessState =
  | { state: "idle" | "running" | "ok" }
  | { state: "error"; error: ApiError; retryable: boolean };

const POLL_MS = 2500;

function asApiError(e: unknown): ApiError {
  return e instanceof ApiError ? e : new ApiError({ status: 0, code: "unknown", message: e instanceof Error ? e.message : String(e) });
}

function hasOutputs(r: RunDetail) {
  return r.status === "failed" || !!(r.outputs.user || r.outputs.dev);
}

/**
 * Everything the run page needs, live:
 *  - GET the run once; if this tab did not already start processing and the run is
 *    still queued, POST /process (the API has no background worker).
 *  - Subscribe to SSE (replay, then tail). On done|failed, close and re-fetch the
 *    run until its outputs are in. If the stream breaks, fall back to polling.
 */
export function useRun(id: string) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [loadError, setLoadError] = useState<ApiError | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [connection, setConnection] = useState<Connection>("connecting");
  const [processState, setProcessState] = useState<ProcessState>(() =>
    processingPromise(id) ? { state: "running" } : { state: "idle" },
  );
  const alive = useRef(true);
  const finishing = useRef(false);
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollTimer.current) clearInterval(pollTimer.current);
    pollTimer.current = null;
  }, []);

  /** Re-fetch after a terminal event until the outputs are there (the API may write them a moment later). */
  const finish = useCallback(async () => {
    if (finishing.current) return;
    finishing.current = true;
    stopPolling();
    for (let attempt = 0; attempt < 6 && alive.current; attempt++) {
      try {
        const r = await getRun(id);
        if (!alive.current) return;
        setRun(r);
        if (isTerminal(r.status) && hasOutputs(r)) return;
      } catch {
        // keep trying; the stream already told us the run ended
      }
      await new Promise((resolve) => setTimeout(resolve, 600 * (attempt + 1)));
    }
  }, [id, stopPolling]);

  const startPolling = useCallback(() => {
    if (pollTimer.current || finishing.current) return;
    setConnection("polling");
    pollTimer.current = setInterval(async () => {
      try {
        const r = await getRun(id);
        if (!alive.current) return;
        setRun(r);
        if (isTerminal(r.status)) {
          setConnection("closed");
          void finish();
        }
      } catch {
        // transient; the next tick retries
      }
    }, POLL_MS);
  }, [id, finish]);

  /** Follow a processing request to its end. Sets state only from its callbacks. */
  const attach = useCallback(
    (p: Promise<ProcessOutcome>) => {
      p.then(
        (outcome) => {
          if (!alive.current) return;
          setProcessState({ state: "ok" });
          if (outcome.outcome === "processed") void finish();
        },
        (e: unknown) => {
          if (!alive.current) return;
          const error = asApiError(e);
          setProcessState({ state: "error", error, retryable: isRetryableProcessError(error) });
        },
      );
    },
    [finish],
  );

  const track = useCallback(
    (p: Promise<ProcessOutcome>) => {
      setProcessState({ state: "running" });
      attach(p);
    },
    [attach],
  );

  const retryProcessing = useCallback(() => {
    track(startProcessing(id, { force: true }));
  }, [id, track]);

  // Initial fetch, and kick off processing if nobody has.
  useEffect(() => {
    alive.current = true;
    const inFlight = processingPromise(id);
    if (inFlight) attach(inFlight);
    getRun(id).then(
      (r) => {
        if (!alive.current) return;
        setRun(r);
        if (!inFlight && r.status === "queued") track(startProcessing(id));
      },
      (e: unknown) => {
        if (alive.current) setLoadError(asApiError(e));
      },
    );
    return () => {
      alive.current = false;
    };
  }, [id, attach, track]);

  // Progress stream.
  useEffect(() => {
    let errors = 0;
    let ended = false;
    let unsubscribe: () => void = () => {};
    unsubscribe = subscribeToRun(id, {
      onOpen: () => {
        errors = 0;
        setConnection("live");
      },
      onEvent: (e) => {
        setEvents((prev) => mergeEvent(prev, e));
        const s = eventStatus(e);
        if (s && isTerminal(s)) {
          ended = true;
          unsubscribe();
          setConnection("closed");
          setRun((prev) => (prev ? { ...prev, status: s } : prev));
          void finish();
        } else if (s) {
          setRun((prev) => (prev && !isTerminal(prev.status) ? { ...prev, status: s } : prev));
        }
      },
      onError: (fatal) => {
        if (ended) return;
        errors += 1;
        // EventSource retries by itself; give up on it after a few failures and poll instead.
        if (fatal || errors >= 3) {
          unsubscribe();
          startPolling();
        }
      },
    });
    return () => {
      unsubscribe();
      stopPolling();
    };
  }, [id, finish, startPolling, stopPolling]);

  return { run, loadError, events, connection, processState, retryProcessing };
}
