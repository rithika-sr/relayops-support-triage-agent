"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, Breadcrumbs, Button, ButtonLink, Card, Empty, ErrorState, Field, Mono, Notice, Select, Skeleton, StatusBadge, TabPanel, Tabs, Textarea, useToast } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { fmtDate, fmtDateUTC, label } from "@/lib/format";
import type { RunSummary, TicketDetail, TimelineItem } from "@/lib/types";
import { TargetBadge } from "./TargetBadge";

const LANE: Record<string, { title: string; cls: string }> = {
  customer_report: { title: "Customer report", cls: "border-l-accent-600" },
  trusted_record: { title: "Record", cls: "border-l-ink-700" },
  signal: { title: "Computed signal", cls: "border-l-warn-700" },
  hypothesis: { title: "Unconfirmed", cls: "border-l-danger-700" },
  staff: { title: "Staff", cls: "border-l-line-strong" },
};

const SOURCE: Record<string, string> = {
  portal: "Customer portal", manual: "Entered by staff", import: "Imported file", connector: "Connected system", seed: "Demo seed", unknown: "Unknown source",
};

function Timeline({ ticketId }: { ticketId: string }) {
  const q = useQuery({ queryKey: ["timeline", ticketId], queryFn: () => api.get<{ items: TimelineItem[] }>(`/tickets/${ticketId}/timeline`) });
  if (q.isLoading) return <Skeleton />;
  if (q.error) return <ErrorState error={q.error} />;
  if (!q.data!.items.length) return <Empty title="No timeline yet">Run an investigation to collect timestamped evidence.</Empty>;
  return (
    <ol className="flex flex-col gap-2">
      {q.data!.items.map((x, i) => (
        <li key={i} className={`rounded-md border border-line border-l-4 bg-card px-3 py-2 text-sm ${LANE[x.lane]?.cls ?? ""}`}>
          <p className="text-xs text-muted">{fmtDateUTC(x.at)} · {LANE[x.lane]?.title ?? x.lane}</p>
          <p>{x.label}</p>
          {x.note ? <p className="text-xs text-warn-700">{x.note}</p> : null}
        </li>
      ))}
    </ol>
  );
}

interface Staff { id: string; name: string }

export function TicketPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();
  const toast = useToast();
  const [tab, setTab] = useState("conversation");
  const [note, setNote] = useState("");
  const [playbook, setPlaybook] = useState("");
  const q = useQuery({ queryKey: ["ticket", id], queryFn: () => api.get<TicketDetail & { ticket: { source_kind?: string; assignee_user_id?: string | null } }>(`/tickets/${id}`), refetchInterval: 15_000 });
  const staff = useQuery({ queryKey: ["staff"], queryFn: () => api.get<Staff[]>("/staff") });
  const start = useMutation<RunSummary, ApiError>({
    mutationFn: () => api.post(`/tickets/${id}/investigations`, { playbook_key: playbook || null }),
    onSuccess: (r) => router.push(`/app/investigations/${r.id}`),
  });
  const addNote = useMutation<unknown, ApiError>({
    mutationFn: () => api.post(`/tickets/${id}/messages`, { body: note, visibility: "internal" }),
    onSuccess: () => { setNote(""); toast("Internal note added"); qc.invalidateQueries({ queryKey: ["ticket", id] }); },
  });
  const patch = useMutation<unknown, ApiError, Record<string, string>>({
    mutationFn: (body) => api.patch(`/tickets/${id}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ticket", id] }),
  });
  const assign = useMutation<unknown, ApiError, string | null>({
    mutationFn: (uid) => api.post(`/tickets/${id}/assign`, { assignee_user_id: uid }),
    onSuccess: () => { toast("Assignment updated"); qc.invalidateQueries({ queryKey: ["ticket", id] }); },
  });
  if (q.isLoading) return <Card><Skeleton lines={6} /></Card>;
  if (q.error) return <ErrorState error={q.error} retry={q.refetch} />;
  const d = q.data!;
  const t = d.ticket;
  const customerMsgs = d.messages.filter((m) => m.visibility === "customer");
  const notes = d.messages.filter((m) => m.visibility === "internal");
  const activeRun = d.runs?.find((r) => ["queued", "running", "executing"].includes(r.status) && r.mode === "live");
  const reviewRun = d.runs?.find((r) => r.status === "awaiting_review" && r.mode === "live");

  return (
    <div>
      <Breadcrumbs items={[{ label: "Support", href: "/app/inbox" }, { label: `Ticket #${t.number}` }]} />
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight">{t.subject}</h1>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted">
            <StatusBadge status={t.status} />{t.priority !== "normal" ? <StatusBadge status={t.priority} /> : null}<TargetBadge target={t.target} />
            {t.restricted ? <Badge tone="danger">restricted security review</Badge> : null}
            <span>{t.account_name} · opened {fmtDate(t.created_at)} · {SOURCE[t.source_kind ?? "unknown"] ?? t.source_kind}</span>
          </p>
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="flex min-w-0 flex-col gap-4">
          {reviewRun ? (
            <Notice tone="warn" title="A drafted response is waiting for review">
              <Link className="font-medium underline" href={`/app/investigations/${reviewRun.id}`}>Review reply</Link>
            </Notice>
          ) : null}
          {activeRun ? <Notice tone="accent">An investigation is in progress. <Link className="underline" href={`/app/investigations/${activeRun.id}`}>Watch it</Link>.</Notice> : null}
          <Tabs label="Ticket" value={tab} onChange={setTab} tabs={[
            { id: "conversation", label: "Conversation", count: customerMsgs.length },
            { id: "notes", label: "Internal notes", count: notes.length },
            { id: "timeline", label: "Evidence timeline" },
          ]} />
          {tab === "conversation" ? (
            <TabPanel id="conversation">
              <ol className="flex flex-col gap-3">
                {customerMsgs.map((m) => (
                  <li key={m.id} className={m.author_kind === "customer" ? "" : "pl-6"}>
                    <div className={`rounded-xl border px-4 py-3 ${m.author_kind === "customer" ? "border-line bg-card" : "border-accent-100 bg-accent-50"}`}>
                      <p className="flex flex-wrap items-center gap-2 text-[13px] text-muted">
                        <span className="font-medium text-text">{m.author_kind === "customer" ? (m.author_name ?? "Customer") : (m.author_name ?? "Support")}</span>
                        {m.action_id ? <Badge tone="ok">approved reply</Badge> : null}
                        {fmtDate(m.created_at)}
                      </p>
                      <p className="mt-1.5 text-[15px] whitespace-pre-wrap">{m.body}</p>
                    </div>
                  </li>
                ))}
              </ol>
              <p className="mt-3 text-[13px] text-muted">Replies to the customer are drafted by an investigation and published only after review.</p>
            </TabPanel>
          ) : tab === "notes" ? (
            <TabPanel id="notes">
              <Notice tone="warn">Internal notes are never shown to the customer.</Notice>
              <ol className="mt-3 flex flex-col gap-2">
                {notes.map((m) => (
                  <li key={m.id} className="rounded-lg border border-warn-100 bg-warn-50 px-4 py-2.5 text-sm">
                    <p className="text-[13px] text-muted"><span className="font-medium text-text">{m.author_name ?? m.author_kind}</span> · {fmtDate(m.created_at)}</p>
                    <p className="mt-1 whitespace-pre-wrap">{m.body}</p>
                  </li>
                ))}
              </ol>
              <form className="mt-3 flex flex-col gap-2" onSubmit={(e) => { e.preventDefault(); addNote.mutate(); }}>
                <Field id="note" label="Add an internal note"><Textarea id="note" value={note} onChange={(e) => setNote(e.target.value)} className="min-h-16" /></Field>
                {addNote.error ? <Notice tone="danger">{addNote.error.detail}</Notice> : null}
                <div><Button type="submit" busy={addNote.isPending} disabled={!note.trim()}>Add note</Button></div>
              </form>
            </TabPanel>
          ) : (
            <TabPanel id="timeline"><Timeline ticketId={t.id} /></TabPanel>
          )}
        </div>

        <aside className="flex flex-col gap-4">
          <Card title="Next step">
            {reviewRun ? (
              <ButtonLink variant="primary" href={`/app/investigations/${reviewRun.id}`} className="w-full">Review reply</ButtonLink>
            ) : (
              <div className="flex flex-col gap-2">
                <label htmlFor="pb" className="text-[13px] text-muted">Investigation playbook</label>
                <Select id="pb" value={playbook} onChange={(e) => setPlaybook(e.target.value)}>
                  <option value="">Choose automatically</option><option value="howto">How-to answer</option><option value="bug">Bug investigation</option>
                  <option value="feature">Feature request</option><option value="incident">Incident triage</option>
                </Select>
                <Button variant="primary" busy={start.isPending} disabled={!!activeRun} onClick={() => start.mutate()}
                  title={activeRun ? "An investigation is already running" : undefined}>Investigate</Button>
                {start.error ? <Notice tone="danger">{start.error.detail}</Notice> : null}
              </div>
            )}
          </Card>
          {d.account ? (
            <Card title={d.account.name}>
              <p className="text-sm">{label(d.account.plan)} plan · version {d.account.product_version}</p>
              <ul className="mt-2 flex flex-wrap gap-1.5">
                {Object.entries(d.account.entitlements).filter(([, v]) => typeof v === "boolean").map(([k, v]) => (
                  <li key={k}><Badge tone={v ? "ok" : "neutral"}>{label(k)}: {v ? "included" : "not included"}</Badge></li>
                ))}
              </ul>
              {t.target?.policy.reasons ? <details className="mt-2 text-[13px]"><summary className="cursor-pointer text-muted">Why this target</summary><ul className="mt-1 list-disc pl-5 text-muted">{t.target.policy.reasons.map((r) => <li key={r}>{r}</li>)}</ul></details> : null}
            </Card>
          ) : null}
          <Card title="Owner and status">
            <div className="flex flex-col gap-2">
              <Select aria-label="Assignee" value={t.assignee_user_id ?? ""} onChange={(e) => assign.mutate(e.target.value || null)}>
                <option value="">Unassigned</option>{staff.data?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </Select>
              <Select aria-label="Status" value={t.status} onChange={(e) => patch.mutate({ status: e.target.value })}>
                {["open", "pending_review", "pending_customer", "resolved", "closed"].map((s) => <option key={s} value={s}>{label(s)}</option>)}
              </Select>
              <Select aria-label="Priority" value={t.priority} onChange={(e) => patch.mutate({ priority: e.target.value })}>
                {["low", "normal", "high", "urgent"].map((s) => <option key={s} value={s}>{s}</option>)}
              </Select>
              {patch.error ?? assign.error ? <Notice tone="danger">{(patch.error ?? assign.error)!.detail}</Notice> : null}
            </div>
          </Card>
          <Card title="Links and receipts">
            {d.issue_links?.length ? d.issue_links.map((l) => <p key={l.issue_id} className="text-sm">{l.key} · {l.title} <StatusBadge status={l.status} /></p>) : <p className="text-sm text-muted">No engineering links.</p>}
            {d.incidents.map((i) => <p key={i.id} className="mt-1 text-sm">Incident: {i.title} <StatusBadge status={i.status} /></p>)}
            {d.actions?.length ? (
              <ul className="mt-2 border-t border-line pt-2 text-[13px] text-muted">
                {d.actions.map((a) => <li key={a.id}>{label(a.kind)} · {a.status} · {fmtDate(a.created_at)}</li>)}
              </ul>
            ) : null}
          </Card>
          <details className="text-[13px] text-muted">
            <summary className="cursor-pointer">Record details</summary>
            <p className="mt-1">Ticket <Mono>{t.id}</Mono> · revision {t.revision} · {t.component ?? "no area"} · version {t.product_version ?? "—"}{t.error_code ? ` · ${t.error_code}` : ""}</p>
            <p className="mt-1">Investigations: {d.runs?.map((r) => <Link key={r.id} className="mr-1 underline" href={`/app/investigations/${r.id}`}>{label(r.status)}</Link>)}</p>
          </details>
        </aside>
      </div>
    </div>
  );
}
