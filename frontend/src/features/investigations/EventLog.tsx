"use client";

import { Badge } from "@/components/ui";
import { fmtDate, label } from "@/lib/format";
import type { RunEvent } from "@/lib/types";

function describe(e: RunEvent): string {
  const p = e.payload as Record<string, unknown>;
  switch (e.kind) {
    case "model_call":
      return `${p.purpose} · ${p.model} · ${p.duration_ms} ms${p.output_tokens ? ` · ${p.output_tokens} tokens` : ""}${p.valid ? "" : ` · invalid: ${p.error}`}`;
    case "decision":
      return `Purpose: ${p.purpose}`;
    case "tool_call":
      return `${p.tool}(${JSON.stringify(p.args)})`;
    case "tool_result":
      return `${p.tool} → ${p.status}: ${p.summary}`;
    case "node_completed":
      return String(p.summary ?? p.rationale ?? (p.stop_reason ? `stop: ${p.stop_reason}` : ""));
    case "proposal_created":
      return `Proposal created · verification ${p.verification}${(p.failed_checks as string[])?.length ? ` (${(p.failed_checks as string[]).join(", ")})` : ""}`;
    case "action_result":
      return `Action ${p.status}${p.reason ? `: ${p.reason}` : ""}`;
    default:
      return Object.entries(p).filter(([k]) => !["evidence", "replayed_from_seq", "recorded_at"].includes(k)).map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join(" · ").slice(0, 240);
  }
}

const TONE: Record<string, "accent" | "warn" | "danger" | "ok" | "neutral"> = {
  model_call: "accent",
  tool_call: "neutral",
  tool_result: "neutral",
  awaiting_review: "warn",
  proposal_created: "warn",
  action_result: "ok",
  run_failed: "danger",
  model_unavailable: "danger",
  run_cancelled: "neutral",
  cancel_requested: "neutral",
};

export function EventLog({ events }: { events: RunEvent[] }) {
  return (
    <ol className="flex flex-col gap-1 text-sm" aria-label="Event timeline">
      {events.map((e) => (
        <li key={e.seq} className="grid grid-cols-[3rem_1fr] gap-2 border-b border-line/60 py-1.5 last:border-0 sm:grid-cols-[3rem_9rem_1fr]">
          <span className="font-mono text-xs text-muted">#{e.seq}</span>
          <span className="hidden text-xs text-muted sm:block">{fmtDate(e.created_at)}</span>
          <span className="min-w-0 break-words">
            <Badge tone={TONE[e.kind] ?? "neutral"}>{label(e.kind)}</Badge>
            {e.node ? <span className="ml-1 text-xs text-muted">{e.node}</span> : null}
            <span className="ml-2">{describe(e)}</span>
            {"replayed_from_seq" in e.payload ? <span className="ml-1 text-xs text-warn-700">(recorded #{String(e.payload.replayed_from_seq)})</span> : null}
          </span>
        </li>
      ))}
    </ol>
  );
}
