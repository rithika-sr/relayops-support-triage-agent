"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, Button, Card, Empty, ErrorState, Loading, Mono, Notice, Select, StatusBadge } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { fmtDate, label, shortHash } from "@/lib/format";
import { useMe } from "@/lib/session";
import type { RunDetail, RunSummary } from "@/lib/types";
import { EventLog } from "./EventLog";
import { EvidenceInspector } from "./EvidenceInspector";
import { ReviewPanel } from "./ReviewPanel";
import { RunGraph } from "./RunGraph";
import { useRunStream } from "./useRunStream";

const ACTIVE = ["queued", "running", "executing"];

function useRunAction(id: string, path: string, onDone: (r: RunSummary) => void) {
  return useMutation<RunSummary, ApiError, unknown>({
    mutationFn: (body) => api.post(`/investigations/${id}/${path}`, body),
    onSuccess: onDone,
  });
}

function Meter({ label: l, used, max }: { label: string; used: number; max: number }) {
  return (
    <div className="text-xs">
      <div className="flex justify-between"><span className="text-muted">{l}</span><span className="tabular-nums">{used} / {max}</span></div>
      <div className="mt-1 h-1.5 rounded bg-line" role="meter" aria-valuenow={used} aria-valuemin={0} aria-valuemax={max} aria-label={l}>
        <div className="h-1.5 rounded bg-teal-600" style={{ width: `${Math.min(100, (used / Math.max(max, 1)) * 100)}%` }} />
      </div>
    </div>
  );
}

export function InvestigationPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const me = useMe();
  const [selected, setSelected] = useState<string | null>(null);
  const [compareMode, setCompareMode] = useState("lexical");
  const q = useQuery({
    queryKey: ["run", id],
    queryFn: () => api.get<RunDetail>(`/investigations/${id}`),
    // Poll while work is in flight, including the gap between an approval and the worker executing it.
    refetchInterval: (query) => {
      const data = query.state.data;
      const approvedPending = data?.run.status === "awaiting_review" && data.proposals.some((p) => p.status === "approved");
      return ACTIVE.includes(data?.run.status ?? "") || approvedPending ? 3000 : false;
    },
  });
  const active = ACTIVE.includes(q.data?.run.status ?? "");
  const live = useRunStream(id, q.data?.last_seq, active);
  const onDone = (r: RunSummary) => {
    qc.invalidateQueries({ queryKey: ["run", id] });
    if (r.id !== id) router.push(`/app/investigations/${r.id}`);
  };
  const cancel = useRunAction(id, "cancel", onDone);
  const retry = useRunAction(id, "retry", onDone);
  const replay = useRunAction(id, "replay", onDone);
  const compare = useRunAction(id, "compare", onDone);

  if (q.isLoading) return <Loading label="Loading investigation" />;
  if (q.error) return <ErrorState error={q.error} retry={q.refetch} />;
  const d = q.data!;
  const r = d.run;
  const current = d.proposals.find((p) => p.status === "pending_review") ?? d.proposals[d.proposals.length - 1];
  const cited = current?.payload.reply_evidence_ids ?? [];
  const internal = current?.payload.internal_evidence_ids ?? [];
  const terminal = ["completed", "failed", "cancelled", "rejected"].includes(r.status);
  const mutErr = cancel.error ?? retry.error ?? replay.error ?? compare.error;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm text-muted">
            {d.ticket ? <Link className="text-teal-700 hover:underline" href={`/app/tickets/${d.ticket.id}`}>#{d.ticket.number} {d.ticket.subject}</Link> : null}
          </p>
          <h1 className="mt-1 flex flex-wrap items-center gap-2 text-xl font-semibold">
            Investigation <Mono>{r.id}</Mono> <StatusBadge status={r.status} />
            {r.mode === "recorded_replay" ? <Badge tone="amber">recorded replay</Badge> : null}
            {r.compare_of_run_id ? <Badge tone="teal">comparison run</Badge> : null}
          </h1>
          <p className="mt-1 text-xs text-muted">
            {r.model_provider === "fixture" ? <Badge tone="danger">fixture provider (test only)</Badge> : null} model {r.model_name}
            {r.model_digest ? <> · digest <Mono>{shortHash(r.model_digest)}</Mono></> : null} · playbook {r.playbook} r{r.playbook_revision} · policy {r.policy_version} ·
            retrieval {String(r.retrieval_config.mode)} · started {fmtDate(r.started_at)}{active ? (live ? " · live" : " · polling") : ""}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {!terminal && r.mode === "live" ? <Button variant="danger" busy={cancel.isPending} onClick={() => cancel.mutate(undefined)}>Cancel run</Button> : null}
          {r.status === "failed" && r.mode === "live" ? <Button variant="primary" busy={retry.isPending} onClick={() => retry.mutate(undefined)}>Retry from checkpoint</Button> : null}
          {r.mode === "live" && !active ? <Button busy={replay.isPending} onClick={() => replay.mutate(undefined)} title="Re-present recorded events. No model calls or actions.">Recorded replay</Button> : null}
          {r.mode === "live" && terminal ? (
            <span className="flex items-center gap-1">
              <label className="sr-only" htmlFor="cmp">Comparison retrieval mode</label>
              <Select id="cmp" value={compareMode} onChange={(e) => setCompareMode(e.target.value)} className="w-28">
                <option value="lexical">lexical</option><option value="dense">dense</option><option value="rrf">rrf</option>
              </Select>
              <Button busy={compare.isPending} onClick={() => compare.mutate({ retrieval_mode: compareMode })} title="New live run; needs its own review">Compare run</Button>
            </span>
          ) : null}
        </div>
      </div>
      {r.mode === "recorded_replay" ? <Notice tone="amber">Recorded replay of <Link className="underline" href={`/app/investigations/${r.replay_of_run_id}`}>{r.replay_of_run_id}</Link>. Events are re-presented from storage; no model, tool, or action ran.</Notice> : null}
      {r.error ? <Notice tone="danger">Run error: {r.error}{r.error.includes("model unavailable") ? " — start Ollama or pull the model, then retry." : ""}</Notice> : null}
      {mutErr ? <Notice tone="danger">{mutErr.detail}</Notice> : null}

      <div className="grid gap-4 xl:grid-cols-[260px_minmax(0,1fr)_340px]">
        <Card title="Graph" className="min-w-0">
          <RunGraph graph={d.graph} />
          <div className="mt-3 flex flex-col gap-2">
            <Meter label="Investigation turns" used={r.usage.turns ?? 0} max={Number(r.budgets.max_turns)} />
            <Meter label="Read-tool calls" used={r.usage.tool_calls ?? 0} max={Number(r.budgets.max_tool_calls)} />
            <p className="text-xs text-muted">Model calls {r.usage.model_calls ?? 0} · repairs {r.usage.repairs ?? 0}/{String(r.budgets.max_repairs)} · deadline {String(r.budgets.deadline_seconds)}s</p>
          </div>
        </Card>
        <Card title="Proposal" className="min-w-0">
          {current ? (
            <ReviewPanel key={`${current?.id ?? ""}`} proposal={current} runId={id} ticketId={d.ticket?.id} canReview={me.data?.role === "admin" || me.data?.role === "support"} onSelectEvidence={setSelected} />
          ) : r.mode === "recorded_replay" ? (
            <Empty title="Replays carry no proposals">Approvals belong to the original live run.</Empty>
          ) : active ? (
            <Loading label="Investigating" />
          ) : (
            <Empty title="No proposal">{r.status === "failed" ? "The run stopped before proposing. Retry resumes from the last checkpoint." : "This run ended without a proposal."}</Empty>
          )}
          {d.proposals.length > 1 ? (
            <p className="mt-3 text-xs text-muted">Versions: {d.proposals.map((p) => `v${p.version} ${p.status}`).join(" · ")}</p>
          ) : null}
          {d.actions.map((a) => (
            <Notice key={a.id} tone={a.status === "succeeded" ? "ok" : "amber"}>
              Action receipt <Mono>{a.id}</Mono>: {label(a.kind)} · {a.status} · {a.adapter} adapter.{" "}
              {String(a.receipt.note ?? "")}
              {a.receipt.engineering_issue_key ? ` Engineering record ${String(a.receipt.engineering_issue_key)}.` : ""}
            </Notice>
          ))}
        </Card>
        <Card title={`Evidence (${Object.keys(d.evidence).length})`} className="min-w-0">
          <EvidenceInspector evidence={d.evidence} cited={cited} internal={internal} selected={selected} onSelect={setSelected} />
        </Card>
      </div>
      <Card title={`Event timeline (${d.events.length})`}>
        <EventLog events={d.events} />
      </Card>
    </div>
  );
}
