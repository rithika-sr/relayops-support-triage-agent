"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, Button, Card, Empty, ErrorState, Field, Input, Loading, Mono, Notice, PageHeader, Select, StatusBadge, Textarea } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { fmtDate, fmtDateUTC, label } from "@/lib/format";
import { useMe } from "@/lib/session";
import type { Candidate, Incident, TimelineItem } from "@/lib/types";

function CandidateCard({ c, window, incidents }: { c: Candidate; window: number; incidents: Incident[] }) {
  const qc = useQueryClient();
  const [title, setTitle] = useState(`${c.component}: ${c.signature}`);
  const [severity, setSeverity] = useState("P3");
  const [target, setTarget] = useState(c.suggested_incidents[0] ?? "");
  const m = useMutation<unknown, ApiError>({
    mutationFn: () => api.post(`/incidents/candidates/${c.key}/confirm`, { title, severity, window_hours: window, incident_id: target || null, expected_ticket_ids: c.tickets.map((t) => t.id) }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["candidates"] }); qc.invalidateQueries({ queryKey: ["incidents"] }); },
  });
  const allLinked = c.tickets.every((t) => t.incident_id);
  return (
    <Card title={<span className="flex flex-wrap items-center gap-1.5"><Badge tone="warn">candidate</Badge><Mono>{c.signature}</Mono> on {c.component} v{c.product_version}</span>}>
      <dl className="grid grid-cols-3 gap-2 text-sm">
        <div><dt className="text-xs text-muted">Tickets</dt><dd className="text-lg font-semibold">{c.ticket_count}</dd></div>
        <div><dt className="text-xs text-muted">Distinct accounts</dt><dd className="text-lg font-semibold">{c.distinct_accounts}</dd></div>
        <div><dt className="text-xs text-muted">Window</dt><dd className="text-xs">{fmtDate(c.first_reported_at)} → {fmtDate(c.last_reported_at)}</dd></div>
      </dl>
      <p className="mt-1 text-xs text-muted">Accounts: {c.accounts.join(", ")} · {c.method}</p>
      <ul className="mt-2 text-sm">{c.tickets.map((t) => <li key={t.id}><Link className="text-accent-700 hover:underline" href={`/app/tickets/${t.id}`}>#{t.number}</Link> {t.subject} <span className="text-xs text-muted">({t.account})</span>{t.incident_id ? <Badge tone="ok">linked</Badge> : null}</li>)}</ul>
      {allLinked ? <Notice tone="ok">All tickets already linked to a reviewed incident.</Notice> : (
        <form className="mt-3 grid gap-2 sm:grid-cols-3" onSubmit={(e) => { e.preventDefault(); m.mutate(); }}>
          <Select aria-label="Link to" value={target} onChange={(e) => setTarget(e.target.value)} className="sm:col-span-3">
            <option value="">Create a new reviewed incident</option>
            {incidents.filter((i) => i.status !== "resolved").map((i) => <option key={i.id} value={i.id}>Link to existing: {i.title}</option>)}
          </Select>
          {!target ? <>
            <Input aria-label="Incident title" value={title} onChange={(e) => setTitle(e.target.value)} className="sm:col-span-2" />
            <Select aria-label="Severity" value={severity} onChange={(e) => setSeverity(e.target.value)}>{["P1", "P2", "P3", "P4"].map((s) => <option key={s}>{s}</option>)}</Select>
          </> : null}
          <div className="sm:col-span-3 flex items-center gap-2">
            <Button variant="warn" type="submit" busy={m.isPending}>Confirm after review</Button>
            <span className="text-xs text-muted">Confirmation records you as reviewer for exactly these {c.ticket_count} tickets. It is not published to customers.</span>
          </div>
          {m.error ? <Notice tone="danger">{m.error.detail}</Notice> : null}
        </form>
      )}
    </Card>
  );
}

interface IncidentDetail { incident: Incident; tickets: { id: string; number: number; subject: string; account: string; created_at: string; status: string }[]; timeline: TimelineItem[] }

function IncidentPanel({ id }: { id: string }) {
  const qc = useQueryClient();
  const router = useRouter();
  const me = useMe();
  const q = useQuery({ queryKey: ["incident", id], queryFn: () => api.get<IncidentDetail>(`/incidents/${id}`) });
  const [summary, setSummary] = useState<string | null>(null);
  const patch = useMutation<unknown, ApiError, Record<string, unknown>>({
    mutationFn: (b) => api.patch(`/incidents/${id}`, b),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["incident", id] }); qc.invalidateQueries({ queryKey: ["incidents"] }); },
  });
  const draft = useMutation<{ artifact_id: string }, ApiError>({ mutationFn: () => api.post(`/incidents/${id}/summary`), onSuccess: () => router.push("/app/artifacts") });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} />;
  const { incident: i, tickets, timeline } = q.data!;
  const pub = summary ?? i.public_summary ?? "";
  return (
    <Card title={i.title}>
      <div className="flex flex-wrap gap-1"><StatusBadge status={i.status} /><Badge>{i.severity}</Badge><Badge>{i.component}</Badge><Badge tone={i.public_visible ? "accent" : "ink"}>{i.public_visible ? "published to customers" : "staff only"}</Badge></div>
      <p className="mt-2 text-sm">{i.linked_tickets} linked tickets · {i.affected_accounts} affected accounts (distinct) · started {fmtDate(i.started_at)}</p>
      {i.internal_notes ? <p className="mt-1 text-xs text-muted">Internal: {i.internal_notes}</p> : null}
      <div className="mt-3 flex flex-wrap gap-2">
        <Select aria-label="Incident status" value={i.status} onChange={(e) => patch.mutate({ status: e.target.value })} className="w-40">{["investigating", "monitoring", "resolved"].map((s) => <option key={s}>{s}</option>)}</Select>
        <Button onClick={() => draft.mutate()} busy={draft.isPending}>Draft summary artifact</Button>
        <a className="inline-flex items-center rounded-md border border-line-strong px-3 py-1.5 text-sm" href="/api/incidents/export.csv">Export CSV</a>
      </div>
      <Field id="pubsum" label="Approved public summary" hint="Customers see only this text, and only after an admin publishes it.">
        <Textarea id="pubsum" value={pub} onChange={(e) => setSummary(e.target.value)} className="min-h-16" />
      </Field>
      <div className="mt-2 flex flex-wrap gap-2">
        <Button onClick={() => patch.mutate({ public_summary: pub })} disabled={pub === (i.public_summary ?? "")}>Save summary</Button>
        {me.data?.role === "admin" ? (
          <Button variant={i.public_visible ? "danger" : "primary"} onClick={() => patch.mutate({ public_visible: !i.public_visible, public_summary: pub })}>{i.public_visible ? "Unpublish" : "Publish to customers"}</Button>
        ) : <span className="text-xs text-muted">Only an admin can publish to customers.</span>}
      </div>
      {patch.error ? <Notice tone="danger">{patch.error.detail}</Notice> : null}
      {draft.error ? <Notice tone="danger">{draft.error.detail}</Notice> : null}
      <h3 className="mt-4 text-sm font-semibold">Tickets</h3>
      <ul className="text-sm">{tickets.map((t) => <li key={t.id}><Link className="text-accent-700 hover:underline" href={`/app/tickets/${t.id}`}>#{t.number}</Link> {t.subject} <span className="text-xs text-muted">({t.account})</span></li>)}</ul>
      <h3 className="mt-4 text-sm font-semibold">Evidence timeline</h3>
      <ol className="mt-1 flex flex-col gap-1 text-sm">{timeline.map((x, n) => (
        <li key={n} className="border-l-4 border-l-line-strong pl-2"><span className="font-mono text-xs text-muted">{fmtDateUTC(x.at)}</span> <Badge>{label(x.lane)}</Badge> {x.label}{x.note ? <span className="ml-1 text-xs text-warn-700">({x.note})</span> : null}</li>
      ))}</ol>
    </Card>
  );
}

export function IncidentsPage() {
  const [window, setWindow] = useState(12);
  const [open, setOpen] = useState<string | null>(null);
  const cands = useQuery({ queryKey: ["candidates", window], queryFn: () => api.get<Candidate[]>(`/incidents/candidates?window_hours=${window}`) });
  const incs = useQuery({ queryKey: ["incidents"], queryFn: () => api.get<Incident[]>("/incidents") });
  return (
    <div>
      <PageHeader title="Incidents" subtitle="Constellations are deterministic groupings within your organization. A candidate is a signal, not a confirmed outage." />
      <div className="grid gap-4 xl:grid-cols-2">
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-2">
            <h2 className="font-semibold">Candidate constellations</h2>
            <label htmlFor="win" className="ml-auto text-sm text-muted">Window</label>
            <Select id="win" value={window} onChange={(e) => setWindow(Number(e.target.value))} className="w-24">{[1, 6, 12, 24, 48].map((h) => <option key={h} value={h}>{h}h</option>)}</Select>
          </div>
          {cands.isLoading ? <Loading /> : cands.error ? <ErrorState error={cands.error} retry={cands.refetch} /> : cands.data!.length === 0 ? <Empty title="No candidate groups in this window" /> : cands.data!.map((c) => <CandidateCard key={c.key} c={c} window={window} incidents={incs.data ?? []} />)}
        </div>
        <div className="flex flex-col gap-3">
          <h2 className="font-semibold">Reviewed incidents</h2>
          {incs.isLoading ? <Loading /> : incs.error ? <ErrorState error={incs.error} /> : incs.data!.length === 0 ? <Empty title="No incidents" /> : (
            <ul className="divide-y divide-line rounded-lg border border-line bg-card">{incs.data!.map((i) => (
              <li key={i.id}><button onClick={() => setOpen(i.id)} aria-pressed={open === i.id} className={`flex w-full flex-wrap items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-paper ${open === i.id ? "bg-accent-50" : ""}`}>
                <span><span className="font-medium">{i.title}</span> <span className="text-xs text-muted">{i.linked_tickets} tickets · {i.affected_accounts} accounts</span></span>
                <span className="flex gap-1"><StatusBadge status={i.status} /><Badge tone={i.public_visible ? "accent" : "ink"}>{i.public_visible ? "public" : "staff only"}</Badge></span>
              </button></li>
            ))}</ul>
          )}
          {open ? <IncidentPanel id={open} /> : null}
        </div>
      </div>
    </div>
  );
}
