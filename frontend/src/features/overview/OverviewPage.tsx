"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, Empty, ErrorState, Loading, PageHeader, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDate, label } from "@/lib/format";
import type { LabelStats, Overview } from "@/lib/types";

export function OverviewPage() {
  const q = useQuery({ queryKey: ["overview"], queryFn: () => api.get<Overview>("/overview"), refetchInterval: 30_000 });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} retry={q.refetch} />;
  const o = q.data!;
  const excluded = Object.entries(o.excluded_tickets_by_class ?? {});
  const components = Object.entries(o.open_by_component).map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count);
  return (
    <div>
      <PageHeader title="Overview" subtitle={`Computed from ${o.data_classes_included.join(", ")} records as of ${fmtDate(o.as_of)}`} />
      {excluded.length ? (
        <p className="mb-3 text-[13px] text-muted">Not counted: {excluded.map(([c, n]) => `${n} ${c} ticket${n === 1 ? "" : "s"}`).join(", ")}.</p>
      ) : null}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Stat label="Open tickets" value={o.open_tickets} />
        <Stat label="Awaiting review" value={o.pending_review_proposals} tone={o.pending_review_proposals ? "warn" : undefined} hint="draft proposals" />
        <Stat label="Targets breached" value={o.breached_targets} tone={o.breached_targets ? "danger" : undefined} hint="no first response yet" />
        <Stat label="Due within 4h" value={o.due_within_4h} />
        <Stat label="Restricted open" value={o.restricted_open} hint="security review" />
      </div>
      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <Card title="Open tickets by component">
          {components.length === 0 ? <Empty title="No open tickets" /> : (
            <div className="h-64" aria-label="Open tickets by component chart">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={components} layout="vertical" margin={{ left: 24 }}>
                  <CartesianGrid horizontal={false} stroke="var(--color-line)" />
                  <XAxis type="number" allowDecimals={false} tick={{ fontSize: 12 }} />
                  <YAxis type="category" dataKey="name" tick={{ fontSize: 12 }} width={90} />
                  <Tooltip />
                  <Bar dataKey="count" fill="var(--color-accent-600)" radius={[0, 3, 3, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>
        <Card title="Tickets created per day (14 days)">
          {o.created_per_day.length === 0 ? <Empty title="No tickets in the last 14 days" /> : (
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={o.created_per_day}>
                  <CartesianGrid vertical={false} stroke="var(--color-line)" />
                  <XAxis dataKey="day" tick={{ fontSize: 11 }} tickFormatter={(d: string) => d.slice(5)} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 12 }} />
                  <Tooltip />
                  <Bar dataKey="count" fill="var(--color-info-700)" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>
        <Card title="Tickets by status">
          <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-3">
            {Object.entries(o.tickets_by_status).map(([s, n]) => (
              <div key={s} className="rounded border border-line px-3 py-2">
                <dt className="text-muted">{label(s)}</dt>
                <dd className="text-lg font-semibold tabular-nums">{n}</dd>
              </div>
            ))}
          </dl>
        </Card>
        <LabelAgreement />
        <Card title="Investigations by status" actions={<Link className="text-sm text-accent-700 hover:underline" href="/app/investigations">All runs</Link>}>
          {Object.keys(o.runs_by_status).length === 0 ? <Empty title="No investigations yet">Open a ticket from the inbox and start one.</Empty> : (
            <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-3">
              {Object.entries(o.runs_by_status).map(([s, n]) => (
                <div key={s} className="rounded border border-line px-3 py-2">
                  <dt className="text-muted">{label(s)}</dt>
                  <dd className="text-lg font-semibold tabular-nums">{n}</dd>
                </div>
              ))}
            </dl>
          )}
        </Card>
      </div>
    </div>
  );
}

function LabelAgreement() {
  const q = useQuery({ queryKey: ["label-stats"], queryFn: () => api.get<LabelStats>("/annotations/stats") });
  const s = q.data;
  return (
    <Card title="Claim checks vs. human labels">
      {!s ? <Loading /> : s.status === "pending" ? (
        <Empty title="No human labels yet">Label claims in a proposal&apos;s Claim support list. Agreement is not estimated without labels.</Empty>
      ) : (
        <div className="text-sm">
          <table className="w-full">
            <thead><tr className="text-left text-muted"><th className="py-1 font-normal">Method</th><th className="font-normal">Agree</th><th className="font-normal">Disagree</th></tr></thead>
            <tbody>
              {Object.entries(s.by_method ?? {}).map(([m, v]) => (
                <tr key={m} className="border-t border-line"><td className="py-1.5">{label(m)}</td><td className="tabular-nums">{v.agree}</td><td className="tabular-nums">{v.disagree}</td></tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-xs text-muted">{s.annotated_claims} labeled claims · {s.annotator_disagreements ?? 0} where annotators disagree (excluded) · {s.note}</p>
        </div>
      )}
    </Card>
  );
}
