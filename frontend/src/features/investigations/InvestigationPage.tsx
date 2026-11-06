"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, Breadcrumbs, Button, Card, Disclosure, Drawer, Empty, ErrorState, Mono, Notice, Select, Skeleton, StatusBadge, TabPanel, Tabs, cx } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { fmtDate, label, shortHash } from "@/lib/format";
import { useMe } from "@/lib/session";
import type { GraphNode, RunDetail, RunSummary } from "@/lib/types";
import { EventLog } from "./EventLog";
import { EvidenceInspector } from "./EvidenceInspector";
import { ReviewPanel, routeSentence } from "./ReviewPanel";
import { RunGraph } from "./RunGraph";
import { useRunStream } from "./useRunStream";

const ACTIVE = ["queued", "running", "executing"];

const STATUS_TEXT: Record<string, string> = {
  queued: "Waiting for the worker",
  running: "Gathering evidence",
  awaiting_review: "Ready for your review",
  executing: "Publishing the approved response",
  completed: "Done",
  rejected: "Draft rejected; nothing was sent",
  failed: "Stopped with an error",
  cancelled: "Cancelled",
};

function useRunAction(id: string, path: string, onDone: (r: RunSummary) => void) {
  return useMutation<RunSummary, ApiError, unknown>({
    mutationFn: (body) => api.post(`/investigations/${id}/${path}`, body),
    onSuccess: onDone,
  });
}

function Progress({ graph }: { graph: GraphNode[] }) {
  const steps = graph.filter((g) => g.id !== "audit_outcome");
  return (
    <ol className="flex flex-wrap gap-x-1 gap-y-2 text-[13px]" aria-label="Progress">
      {steps.map((g, i) => (
        <li key={g.id} className="flex items-center gap-1">
          <span className={cx("inline-flex items-center gap-1.5 rounded-full px-2 py-0.5",
            g.state === "completed" ? "bg-ok-50 text-ok-700" : g.state === "waiting" ? "bg-warn-50 text-warn-700"
              : g.state === "active" ? "bg-accent-50 text-accent-700" : g.state === "failed" ? "bg-danger-50 text-danger-700" : "bg-sunken text-muted")}>
            <span aria-hidden>{g.state === "completed" ? "✓" : g.state === "waiting" ? "…" : g.state === "failed" ? "!" : String(i + 1)}</span>
            {g.label.replace(" (interrupt)", "").replace(" (public evidence only)", "")}
            <span className="sr-only">: {g.state}</span>
          </span>
          {i < steps.length - 1 ? <span aria-hidden className="text-subtle">›</span> : null}
        </li>
      ))}
    </ol>
  );
}

export function InvestigationPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const me = useMe();
  const [tab, setTab] = useState("summary");
  const [selected, setSelected] = useState<string | null>(null);
  const [diag, setDiag] = useState(false);
  const [compareMode, setCompareMode] = useState("lexical");
  const q = useQuery({
    queryKey: ["run", id],
    queryFn: () => api.get<RunDetail>(`/investigations/${id}`),
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

  if (q.isLoading) return <Card><Skeleton lines={6} /></Card>;
  if (q.error) return <ErrorState error={q.error} retry={q.refetch} />;
  const d = q.data!;
  const r = d.run;
  const current = d.proposals.find((p) => p.status === "pending_review") ?? d.proposals[d.proposals.length - 1];
  const previous = current ? d.proposals.find((p) => p.version === current.version - 1) : undefined;
  const cited = current?.payload.reply_evidence_ids ?? [];
  const internal = current?.payload.internal_evidence_ids ?? [];
  const terminal = ["completed", "failed", "cancelled", "rejected"].includes(r.status);
  const mutErr = cancel.error ?? retry.error ?? replay.error ?? compare.error;
  const keyEvidence = [...cited, ...internal].filter((x, i, a) => a.indexOf(x) === i && d.evidence[x]).slice(0, 4);
  const openEvidence = (eid: string) => { setSelected(eid); setTab("evidence"); };

  return (
    <div className="flex flex-col gap-5">
      <div>
        <Breadcrumbs items={[{ label: "Support", href: "/app/inbox" }, ...(d.ticket ? [{ label: `Ticket #${d.ticket.number}`, href: `/app/tickets/${d.ticket.id}` }] : []), { label: "Investigation" }]} />
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-2xl font-semibold tracking-tight">{d.ticket?.subject ?? "Investigation"}</h1>
            <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted">
              <StatusBadge status={r.status} /> {STATUS_TEXT[r.status] ?? r.status}
              {r.mode === "recorded_replay" ? <Badge tone="warn">recorded replay</Badge> : null}
              {r.compare_of_run_id ? <Badge tone="info">comparison run</Badge> : null}
              {r.model_provider === "fixture" ? <Badge tone="danger">test model</Badge> : null}
              {active ? <span>{live ? "Updating live" : "Refreshing"}</span> : null}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {!terminal && r.mode === "live" ? <Button variant="danger" busy={cancel.isPending} onClick={() => cancel.mutate(undefined)}>Cancel</Button> : null}
            {r.status === "failed" && r.mode === "live" ? <Button variant="primary" busy={retry.isPending} onClick={() => retry.mutate(undefined)}>Retry from checkpoint</Button> : null}
            <Button variant="ghost" onClick={() => setDiag(true)}>Diagnostics</Button>
          </div>
        </div>
      </div>

      <Progress graph={d.graph} />
      {r.mode === "recorded_replay" ? <Notice tone="warn">Recorded replay of <Link className="underline" href={`/app/investigations/${r.replay_of_run_id}`}>the original run</Link>. Events are shown from storage; nothing ran again and nothing can be approved here.</Notice> : null}
      {r.error ? <Notice tone="danger" title="The run stopped">{r.error}{r.error.includes("model unavailable") ? " Start the local model and retry; RelayOps never substitutes a canned answer." : ""}</Notice> : null}
      {mutErr ? <Notice tone="danger">{mutErr.detail}</Notice> : null}

      <Tabs label="Investigation" value={tab} onChange={setTab} tabs={[
        { id: "summary", label: "Summary" },
        { id: "evidence", label: "Evidence", count: Object.keys(d.evidence).length },
        { id: "activity", label: "Activity", count: d.events.length },
      ]} />

      {tab === "summary" ? (
        <TabPanel id="summary">
          <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
            <Card>
              {current ? (
                <ReviewPanel key={current.id} proposal={current} previous={previous} runId={id} ticketId={d.ticket?.id}
                  canReview={me.data?.role === "admin" || me.data?.role === "support"} onSelectEvidence={openEvidence} />
              ) : r.mode === "recorded_replay" ? (
                <Empty title="Replays carry no drafts">Review and approval belong to the original run.</Empty>
              ) : active ? (
                <div><p className="font-medium">Gathering evidence…</p><p className="mt-1 text-sm text-muted">The draft appears here when the investigation finishes.</p><Skeleton lines={4} /></div>
              ) : (
                <Empty title="No draft">{r.status === "failed" ? "The run stopped before drafting. Retry resumes from the last saved step." : "This run ended without a draft."}</Empty>
              )}
            </Card>
            <div className="flex flex-col gap-4">
              {current ? <Card title="Recommended next step"><p className="text-sm">{routeSentence(current)}</p></Card> : null}
              <Card title="Key evidence">
                {keyEvidence.length ? (
                  <ul className="flex flex-col gap-2 text-sm">
                    {keyEvidence.map((eid) => {
                      const e = d.evidence[eid];
                      return (
                        <li key={eid}>
                          <button className="text-left hover:underline" onClick={() => openEvidence(eid)}>{e.title}</button>
                          <p className="text-xs text-muted">{e.visibility === "public" ? "Customer-visible source" : "Internal only"}{e.source_type === "deployment" ? " · timing is correlation, not cause" : ""}</p>
                        </li>
                      );
                    })}
                  </ul>
                ) : <p className="text-sm text-muted">No evidence cited yet.</p>}
              </Card>
              {d.actions.length ? (
                <Card title="What happened">
                  {d.actions.map((a) => (
                    <p key={a.id} className="text-sm"><StatusBadge status={a.status} /> {label(a.kind)}. {String(a.receipt.note ?? "")}{a.receipt.engineering_issue_key ? ` Engineering record ${String(a.receipt.engineering_issue_key)}.` : ""}</p>
                  ))}
                </Card>
              ) : null}
              <Disclosure summary="Workflow detail">
                <RunGraph graph={d.graph} />
                <p className="mt-2 text-xs text-muted">{r.usage.turns ?? 0} of {String(r.budgets.max_turns)} investigation turns · {r.usage.tool_calls ?? 0} of {String(r.budgets.max_tool_calls)} tool calls · {r.usage.model_calls ?? 0} model calls</p>
              </Disclosure>
              {r.mode === "live" && terminal ? (
                <Disclosure summary="Replay or compare">
                  <div className="flex flex-col gap-2">
                    <Button busy={replay.isPending} onClick={() => replay.mutate(undefined)}>Recorded replay (no effects)</Button>
                    <div className="flex gap-2">
                      <Select aria-label="Comparison retrieval mode" value={compareMode} onChange={(e) => setCompareMode(e.target.value)}>
                        <option value="lexical">lexical retrieval</option><option value="dense">dense retrieval</option><option value="rrf">fused retrieval</option>
                      </Select>
                      <Button busy={compare.isPending} onClick={() => compare.mutate({ retrieval_mode: compareMode })}>New comparison run</Button>
                    </div>
                    <p className="text-xs text-muted">A comparison run is new and needs its own review.</p>
                  </div>
                </Disclosure>
              ) : null}
            </div>
          </div>
        </TabPanel>
      ) : tab === "evidence" ? (
        <TabPanel id="evidence">
          <EvidenceInspector evidence={d.evidence} cited={cited} internal={internal} selected={selected} onSelect={setSelected} />
        </TabPanel>
      ) : (
        <TabPanel id="activity">
          <Card><EventLog events={d.events} /></Card>
        </TabPanel>
      )}

      <Drawer open={diag} onClose={() => setDiag(false)} title="Diagnostics">
        <dl className="grid grid-cols-[9rem_1fr] gap-x-3 gap-y-2 text-sm">
          <dt className="text-muted">Run</dt><dd><Mono>{r.id}</Mono></dd>
          <dt className="text-muted">Thread</dt><dd><Mono>{r.thread_id}</Mono></dd>
          <dt className="text-muted">Model</dt><dd>{r.model_provider} / {r.model_name}</dd>
          <dt className="text-muted">Model digest</dt><dd><Mono>{shortHash(r.model_digest)}</Mono></dd>
          <dt className="text-muted">Prompt hash</dt><dd><Mono>{shortHash(r.prompt_hash)}</Mono></dd>
          <dt className="text-muted">Playbook</dt><dd>{r.playbook} revision {r.playbook_revision}</dd>
          <dt className="text-muted">Policy</dt><dd>{r.policy_version}</dd>
          <dt className="text-muted">Retrieval</dt><dd>{String(r.retrieval_config.mode)} · {String(r.retrieval_config.embed_model)}</dd>
          <dt className="text-muted">Ticket revision</dt><dd>{r.ticket_revision}</dd>
          <dt className="text-muted">Started</dt><dd>{fmtDate(r.started_at)}</dd>
          {current ? <><dt className="text-muted">Payload hash</dt><dd><Mono>{current.payload_hash}</Mono></dd><dt className="text-muted">Evidence hash</dt><dd><Mono>{current.evidence_hash}</Mono></dd></> : null}
        </dl>
        <h3 className="mt-5 text-sm font-semibold">Budgets</h3>
        <pre className="mt-1 overflow-x-auto rounded bg-sunken p-3 text-xs">{JSON.stringify(r.budgets, null, 2)}</pre>
        <h3 className="mt-5 text-sm font-semibold">Recent raw events</h3>
        <pre className="mt-1 max-h-96 overflow-auto rounded bg-sunken p-3 text-xs">{JSON.stringify(d.events.slice(-40), null, 2)}</pre>
      </Drawer>
    </div>
  );
}
