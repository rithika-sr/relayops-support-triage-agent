"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, Card, Empty, ErrorState, Loading, PageHeader, Select, StatusBadge } from "@/components/ui";
import { api, qs } from "@/lib/api";
import { label } from "@/lib/format";
import type { Issue } from "@/lib/types";
import { COMPONENTS } from "@/features/portal/NewTicketForm";

interface Board {
  columns: Record<string, Issue[]>;
  duplicate_candidates: { component: string; signature: string; issues: string[]; note: string }[];
  owners: { component: string; team: string; escalation: string }[];
}
interface IssueDetail { issue: Issue; tickets: { id: string; number: number; subject: string; status: string; product_version: string | null; link_kind: string; historical: boolean }[]; distinct_accounts: number }

function IssuePanel({ id }: { id: string }) {
  const q = useQuery({ queryKey: ["issue", id], queryFn: () => api.get<IssueDetail>(`/engineering/issues/${id}`) });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} />;
  const { issue: i, tickets, distinct_accounts } = q.data!;
  return (
    <Card title={`${i.key}: ${i.title}`}>
      <div className="flex flex-wrap gap-1"><StatusBadge status={i.status} /><Badge>{i.kind}</Badge><Badge>{i.component}</Badge>{i.origin === "local_handoff" ? <Badge tone="accent">local handoff</Badge> : null}</div>
      <p className="mt-2 text-sm">{i.description}</p>
      <p className="mt-1 text-xs text-muted">Affected {i.affected_versions.join(", ") || "n/a"}{i.fixed_in_version ? ` · fixed in ${i.fixed_in_version}` : ""} · signature {i.error_signature ?? "—"} · owner {i.owner_team}</p>
      <h3 className="mt-3 text-sm font-semibold">Linked tickets ({tickets.length}, {distinct_accounts} accounts)</h3>
      {tickets.length ? <ul className="text-sm">{tickets.map((t) => <li key={t.id}>{t.historical ? <span className="text-muted">#{t.number} {t.subject}</span> : <Link className="text-accent-700 hover:underline" href={`/app/tickets/${t.id}`}>#{t.number} {t.subject}</Link>} <Badge>{label(t.link_kind)}</Badge>{t.historical ? <Badge>historical</Badge> : null}</li>)}</ul> : <p className="text-sm text-muted">None.</p>}
    </Card>
  );
}

export function EngineeringPage() {
  const [component, setComponent] = useState("");
  const [kind, setKind] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const q = useQuery({ queryKey: ["board", component, kind], queryFn: () => api.get<Board>(`/engineering/board${qs({ component, kind })}`) });
  return (
    <div>
      <PageHeader title="Engineering" subtitle="Local issue records. Approved handoffs create LOCAL-n issues here; nothing is written to GitHub or Jira." />
      <div className="mb-3 grid max-w-md gap-2 sm:grid-cols-2">
        <Select aria-label="Component" value={component} onChange={(e) => setComponent(e.target.value)}><option value="">All components</option>{COMPONENTS.map((c) => <option key={c}>{c}</option>)}</Select>
        <Select aria-label="Kind" value={kind} onChange={(e) => setKind(e.target.value)}><option value="">Bugs and features</option><option value="bug">Bugs</option><option value="feature">Feature requests</option></Select>
      </div>
      {q.isLoading ? <Loading /> : q.error ? <ErrorState error={q.error} retry={q.refetch} /> : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
          <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-4">
            {Object.entries(q.data!.columns).map(([status, issues]) => (
              <section key={status} aria-label={label(status)} className="rounded-lg border border-line bg-card/60 p-2">
                <h2 className="mb-2 flex items-center justify-between px-1 text-sm font-semibold">{label(status)}<Badge>{issues.length}</Badge></h2>
                {issues.length === 0 ? <p className="px-1 text-xs text-muted">None</p> : (
                  <ul className="flex flex-col gap-2">{issues.map((i) => (
                    <li key={i.id}>
                      <button onClick={() => setOpen(i.id)} aria-pressed={open === i.id} className={`w-full rounded-md border px-2.5 py-2 text-left text-sm ${open === i.id ? "border-accent-600 bg-accent-50" : "border-line bg-white hover:bg-paper"}`}>
                        <span className="font-mono text-xs text-muted">{i.key}</span> <span className="font-medium">{i.title}</span>
                        <span className="mt-1 flex flex-wrap gap-1"><Badge>{i.component}</Badge>{i.kind === "feature" ? <Badge tone="accent">feature</Badge> : null}{i.affected_versions.map((v) => <Badge key={v}>v{v}</Badge>)}{i.linked_tickets ? <Badge tone="warn">{i.linked_tickets} tickets</Badge> : null}</span>
                      </button>
                    </li>
                  ))}</ul>
                )}
              </section>
            ))}
          </div>
          <div className="flex flex-col gap-4">
            {open ? <IssuePanel id={open} /> : <Empty title="Select an issue">See linked tickets and affected accounts.</Empty>}
            <Card title="Duplicate candidates">
              {q.data!.duplicate_candidates.length === 0 ? <p className="text-sm text-muted">None.</p> : q.data!.duplicate_candidates.map((d) => (
                <p key={d.signature + d.component} className="text-sm"><span className="font-mono">{d.signature}</span> on {d.component}: {d.issues.join(", ")} <span className="text-xs text-muted">({d.note})</span></p>
              ))}
            </Card>
            <Card title="Ownership map">
              <table className="w-full text-sm"><tbody>{q.data!.owners.map((o) => <tr key={o.component} className="border-b border-line/60 last:border-0"><td className="py-1">{o.component}</td><td className="py-1">{o.team}</td><td className="py-1 text-xs text-muted">{o.escalation}</td></tr>)}</tbody></table>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
