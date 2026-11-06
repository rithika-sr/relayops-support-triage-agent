"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, Button, Card, Empty, ErrorState, Field, Loading, Mono, Notice, Select, StatusBadge, Textarea } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { fmtDate, fmtDateUTC, label } from "@/lib/format";
import type { RunDetail, RunSummary, TicketDetail, TimelineItem } from "@/lib/types";
import { ReviewPanel } from "@/features/investigations/ReviewPanel";
import { TargetBadge } from "./TargetBadge";

const LANE_STYLE: Record<string, string> = {
  customer_report: "border-l-teal-600",
  trusted_record: "border-l-ink-700",
  signal: "border-l-amber-700",
  hypothesis: "border-l-danger-700 border-dashed",
  staff: "border-l-line-strong",
};

function Timeline({ ticketId }: { ticketId: string }) {
  const q = useQuery({ queryKey: ["timeline", ticketId], queryFn: () => api.get<{ items: TimelineItem[]; legend: Record<string, string> }>(`/tickets/${ticketId}/timeline`) });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} />;
  const { items, legend } = q.data!;
  return (
    <div>
      <ul className="mb-3 flex flex-wrap gap-3 text-xs text-muted">
        {Object.entries(legend).map(([k, v]) => <li key={k} className={`border-l-4 pl-1.5 ${LANE_STYLE[k]}`}>{v}</li>)}
      </ul>
      {items.length === 0 ? <Empty title="No timeline yet" /> : (
        <ol className="flex flex-col gap-1.5">
          {items.map((x, i) => (
            <li key={i} className={`border-l-4 bg-white px-3 py-1.5 text-sm ${LANE_STYLE[x.lane] ?? ""}`}>
              <span className="font-mono text-xs text-muted">{fmtDateUTC(x.at)}</span> <span>{x.label}</span>
              {x.note ? <Badge tone="amber">{x.note}</Badge> : null}
              <span className="ml-1 text-xs text-muted">source <Mono>{x.source}</Mono>{x.as_of ? ` · as of ${fmtDate(x.as_of)}` : ""}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function PendingReview({ runId, ticketId }: { runId: string; ticketId: string }) {
  const q = useQuery({ queryKey: ["run", runId], queryFn: () => api.get<RunDetail>(`/investigations/${runId}`) });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} />;
  const p = q.data!.proposals.find((x) => x.status === "pending_review");
  if (!p) return null;
  return <ReviewPanel key={p.id} proposal={p} runId={runId} ticketId={ticketId} canReview />;
}

export function TicketPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const [tab, setTab] = useState<"conversation" | "timeline">("conversation");
  const [note, setNote] = useState("");
  const [playbook, setPlaybook] = useState("");
  const q = useQuery({ queryKey: ["ticket", id], queryFn: () => api.get<TicketDetail>(`/tickets/${id}`), refetchInterval: 15_000 });
  const start = useMutation<RunSummary, ApiError>({
    mutationFn: () => api.post(`/tickets/${id}/investigations`, { playbook_key: playbook || null }),
    onSuccess: (r) => router.push(`/app/investigations/${r.id}`),
  });
  const addNote = useMutation<unknown, ApiError>({
    mutationFn: () => api.post(`/tickets/${id}/messages`, { body: note, visibility: "internal" }),
    onSuccess: () => { setNote(""); qc.invalidateQueries({ queryKey: ["ticket", id] }); },
  });
  const patch = useMutation<unknown, ApiError, Record<string, string>>({
    mutationFn: (body) => api.patch(`/tickets/${id}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ticket", id] }),
  });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} retry={q.refetch} />;
  const d = q.data!;
  const t = d.ticket;
  const activeRun = d.runs?.find((r) => ["queued", "running", "executing"].includes(r.status) && r.mode === "live");
  const reviewRun = d.runs?.find((r) => r.status === "awaiting_review" && r.mode === "live");

  return (
    <div className="flex flex-col gap-4">
      <Link href="/app/inbox" className="text-sm text-teal-700 hover:underline">← Inbox</Link>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold"><span className="text-muted">#{t.number}</span> {t.subject}</h1>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-sm">
            <StatusBadge status={t.status} /><StatusBadge status={t.priority} /><TargetBadge target={t.target} />
            {t.restricted ? <Badge tone="danger">restricted security review</Badge> : null}
            <span className="text-muted">rev {t.revision} · {t.component ?? "no component"} · v{t.product_version ?? "—"} {t.error_code ? `· ${t.error_code}` : ""}</span>
          </div>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <div>
            <label htmlFor="pb" className="block text-xs text-muted">Playbook</label>
            <Select id="pb" value={playbook} onChange={(e) => setPlaybook(e.target.value)} className="w-44">
              <option value="">Auto-select</option><option value="howto">How-to resolution</option><option value="bug">Bug investigation</option><option value="feature">Feature request</option><option value="incident">Incident triage</option>
            </Select>
          </div>
          <Button variant="primary" busy={start.isPending} disabled={!!activeRun} title={activeRun ? "An investigation is already running" : undefined} onClick={() => start.mutate()}>
            Launch investigation
          </Button>
        </div>
      </div>
      {start.error ? <Notice tone="danger">{start.error.detail}</Notice> : null}
      {activeRun ? <Notice tone="teal">Investigation <Link className="underline" href={`/app/investigations/${activeRun.id}`}>{activeRun.id}</Link> is {label(activeRun.status)}.</Notice> : null}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="flex min-w-0 flex-col gap-4">
          {reviewRun ? (
            <Card title={<span className="flex items-center gap-2">Draft awaiting review <Badge tone="amber">pending</Badge></span>} actions={<Link className="text-sm text-teal-700 hover:underline" href={`/app/investigations/${reviewRun.id}`}>Open workspace</Link>}>
              <PendingReview runId={reviewRun.id} ticketId={t.id} />
            </Card>
          ) : null}
          <div role="tablist" className="flex gap-1 border-b border-line">
            {(["conversation", "timeline"] as const).map((k) => (
              <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)} className={`-mb-px border-b-2 px-3 py-1.5 text-sm ${tab === k ? "border-teal-600 font-medium" : "border-transparent text-muted"}`}>
                {k === "conversation" ? "Conversation" : "Evidence timeline"}
              </button>
            ))}
          </div>
          {tab === "conversation" ? (
            <Card>
              <ol className="flex flex-col gap-3">
                {d.messages.map((m) => (
                  <li key={m.id} className={`rounded-lg border px-3 py-2 ${m.visibility === "internal" ? "border-amber-100 bg-amber-50" : m.author_kind === "customer" ? "border-line bg-white" : "border-teal-100 bg-teal-50"}`}>
                    <p className="flex flex-wrap items-center gap-1 text-xs text-muted">
                      <span className="font-medium text-text">{m.author_name ?? m.author_kind}</span>
                      <Badge tone={m.visibility === "internal" ? "amber" : "teal"}>{m.visibility === "internal" ? "internal note" : "customer-visible"}</Badge>
                      {m.action_id ? <Badge tone="ok">approved action <Mono>{m.action_id}</Mono></Badge> : null}
                      {fmtDate(m.created_at)}
                    </p>
                    <p className="mt-1 text-sm whitespace-pre-wrap">{m.body}</p>
                  </li>
                ))}
              </ol>
              <form className="mt-4 flex flex-col gap-2" onSubmit={(e) => { e.preventDefault(); addNote.mutate(); }}>
                <Field id="note" label="Internal note" hint="Never shown to the customer. Customer replies go through a reviewed proposal.">
                  <Textarea id="note" value={note} onChange={(e) => setNote(e.target.value)} className="min-h-16" />
                </Field>
                {addNote.error ? <Notice tone="danger">{addNote.error.detail}</Notice> : null}
                <div><Button type="submit" busy={addNote.isPending} disabled={!note.trim()}>Add internal note</Button></div>
              </form>
            </Card>
          ) : (
            <Card><Timeline ticketId={t.id} /></Card>
          )}
        </div>
        <div className="flex flex-col gap-4">
          {d.account ? (
            <Card title="Account context">
              <p className="font-medium">{d.account.name}</p>
              <p className="text-sm text-muted">{d.account.plan} plan · version {d.account.product_version} · {d.account.region}</p>
              <dl className="mt-2 grid grid-cols-2 gap-x-2 gap-y-0.5 text-xs">
                {Object.entries(d.account.entitlements).map(([k, v]) => (
                  <div key={k} className="contents"><dt className="text-muted">{label(k)}</dt><dd>{typeof v === "boolean" ? (v ? "yes" : "no") : v.toLocaleString()}</dd></div>
                ))}
              </dl>
              {t.target?.policy.reasons ? <ul className="mt-2 list-disc pl-4 text-xs text-muted">{t.target.policy.reasons.map((r) => <li key={r}>{r}</li>)}</ul> : null}
            </Card>
          ) : null}
          <Card title="Status">
            <div className="flex flex-col gap-2">
              <Select aria-label="Ticket status" value={t.status} onChange={(e) => patch.mutate({ status: e.target.value })}>
                {["open", "pending_review", "pending_customer", "resolved", "closed"].map((s) => <option key={s} value={s}>{label(s)}</option>)}
              </Select>
              <Select aria-label="Priority" value={t.priority} onChange={(e) => patch.mutate({ priority: e.target.value })}>
                {["low", "normal", "high", "urgent"].map((s) => <option key={s} value={s}>{s}</option>)}
              </Select>
              {patch.error ? <Notice tone="danger">{patch.error.detail}</Notice> : null}
            </div>
          </Card>
          <Card title="Investigations">
            {d.runs?.length ? (
              <ul className="flex flex-col gap-1 text-sm">{d.runs.map((r) => (
                <li key={r.id} className="flex items-center justify-between gap-2"><Link className="font-mono text-xs text-teal-700 hover:underline" href={`/app/investigations/${r.id}`}>{r.id.slice(0, 14)}…</Link><span className="flex gap-1">{r.mode !== "live" ? <Badge tone="amber">replay</Badge> : null}<StatusBadge status={r.status} /></span></li>
              ))}</ul>
            ) : <p className="text-sm text-muted">None yet.</p>}
          </Card>
          <Card title="Action receipts">
            {d.actions?.length ? d.actions.map((a) => (
              <div key={a.id} className="mb-2 text-sm"><StatusBadge status={a.status} /> {label(a.kind)} <span className="text-xs text-muted">({a.adapter}, {fmtDate(a.created_at)})</span>
                {a.receipt.engineering_issue_key ? <p className="text-xs">Engineering: {String(a.receipt.engineering_issue_key)}</p> : null}</div>
            )) : <p className="text-sm text-muted">No approved actions yet. Drafts never change the ticket by themselves.</p>}
          </Card>
          <Card title="Engineering and incidents">
            {d.issue_links?.length ? d.issue_links.map((l) => <p key={l.issue_id} className="text-sm"><Badge>{l.link_kind}</Badge> {l.key} {l.title} <StatusBadge status={l.status} /></p>) : <p className="text-sm text-muted">No linked issues.</p>}
            {d.incidents.map((i) => <p key={i.id} className="mt-1 text-sm"><Badge tone="amber">incident</Badge> {i.title} <StatusBadge status={i.status} /></p>)}
          </Card>
        </div>
      </div>
    </div>
  );
}
