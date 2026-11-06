"use client";

import { Badge, Empty, Mono } from "@/components/ui";
import { fmtDate, shortHash } from "@/lib/format";
import type { Evidence } from "@/lib/types";

const TYPE_LABEL: Record<string, string> = {
  knowledge: "document",
  case: "historical case",
  issue: "engineering issue",
  incident: "incident",
  deployment: "deployment",
  error_aggregate: "error aggregate",
};

export function EvidenceInspector({
  evidence,
  cited,
  internal,
  selected,
  onSelect,
}: {
  evidence: Record<string, Evidence>;
  cited: string[];
  internal: string[];
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const ids = Object.keys(evidence).sort((a, b) => Number(a.slice(1)) - Number(b.slice(1)));
  if (!ids.length) return <Empty title="No evidence yet">Tool observations appear here as the investigation runs.</Empty>;
  return (
    <ul className="flex flex-col gap-2" aria-label="Evidence">
      {ids.map((id) => {
        const e = evidence[id];
        const isSel = selected === id;
        return (
          <li key={id}>
            <button
              onClick={() => onSelect(id)}
              aria-pressed={isSel}
              className={`w-full rounded-md border px-3 py-2 text-left text-sm ${isSel ? "border-accent-600 bg-accent-50" : "border-line bg-white hover:bg-paper"}`}
            >
              <div className="flex flex-wrap items-center gap-1">
                <span className="font-mono text-xs font-semibold">{id}</span>
                <Badge>{TYPE_LABEL[e.source_type] ?? e.source_type}</Badge>
                <Badge tone={e.visibility === "public" ? "accent" : "ink"}>{e.visibility}</Badge>
                {e.kind === "policy" ? <Badge tone="ok">current policy</Badge> : null}
                {e.source_type === "case" ? <Badge tone="warn" title="Lower authority than current policy">historical</Badge> : null}
                {cited.includes(id) ? <Badge tone="accent">cited in reply</Badge> : null}
                {internal.includes(id) ? <Badge tone="neutral">used internally</Badge> : null}
              </div>
              <p className="mt-1 font-medium">{e.title}</p>
              <p className={`mt-0.5 text-xs text-muted ${isSel ? "" : "line-clamp-2"}`}>{e.excerpt}</p>
              {isSel ? (
                <dl className="mt-2 grid grid-cols-2 gap-x-2 gap-y-1 text-xs">
                  <dt className="text-muted">Source</dt><dd className="truncate"><Mono>{e.source_id}</Mono></dd>
                  <dt className="text-muted">Version</dt><dd>{e.version ?? "—"}</dd>
                  <dt className="text-muted">Content hash</dt><dd><Mono title={e.content_hash ?? ""}>{shortHash(e.content_hash)}</Mono></dd>
                  <dt className="text-muted">Snapshot hash</dt><dd><Mono title={e.snapshot_hash}>{shortHash(e.snapshot_hash)}</Mono></dd>
                  <dt className="text-muted">Time</dt><dd>{fmtDate(e.timestamp)}</dd>
                  {e.source_type === "deployment" ? <><dt className="text-muted">Note</dt><dd>timing is correlation, not cause</dd></> : null}
                </dl>
              ) : null}
            </button>
          </li>
        );
      })}
    </ul>
  );
}
