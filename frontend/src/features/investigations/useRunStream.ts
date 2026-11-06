"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

/** Subscribe to a run's persisted events over SSE (sequence-resumable); refresh the detail query on change. */
export function useRunStream(runId: string, lastSeq: number | undefined, active: boolean) {
  const qc = useQueryClient();
  const [connected, setConnected] = useState(false);
  const seqRef = useRef(lastSeq ?? 0);
  useEffect(() => {
    seqRef.current = Math.max(seqRef.current, lastSeq ?? 0);
  }, [lastSeq]);

  useEffect(() => {
    if (!active || typeof EventSource === "undefined") return;
    const es = new EventSource(`/api/investigations/${runId}/stream?after=${seqRef.current}`);
    let timer: ReturnType<typeof setTimeout> | null = null;
    const refresh = () => {
      if (timer) return;
      timer = setTimeout(() => {
        timer = null;
        qc.invalidateQueries({ queryKey: ["run", runId] });
      }, 300);
    };
    es.onopen = () => setConnected(true);
    es.addEventListener("run_event", (e) => {
      const seq = Number((e as MessageEvent).lastEventId);
      if (seq > seqRef.current) {
        seqRef.current = seq;
        refresh();
      }
    });
    es.addEventListener("end", () => {
      refresh();
      es.close();
      setConnected(false);
    });
    es.onerror = () => setConnected(false);
    return () => {
      es.close();
      if (timer) clearTimeout(timer);
    };
  }, [runId, active, qc]);
  return connected;
}
