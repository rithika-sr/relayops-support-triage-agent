"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, Empty, ErrorState, Loading, PageHeader, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDate, label } from "@/lib/format";
import type { Overview } from "@/lib/types";

export function OverviewPage() {
  const q = useQuery({ queryKey: ["overview"], queryFn: () => api.get<Overview>("/overview"), refetchInterval: 30_000 });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} retry={q.refetch} />;
  const o = q.data!;
  const components = Object.entries(o.open_by_component).map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count);
  return (
    <div>
      <PageHeader title="Overview" subtitle={`Computed from current records as of ${fmtDate(o.as_of)}`} />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Stat label="Open tickets" value={o.open_tickets} />
        <Stat label="Awaiting review" value={o.pending_review_proposals} tone={o.pending_review_proposals ? "amber" : undefined} hint="draft proposals" />
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
                  <CartesianGrid horizontal={false} stroke="#e5ddd0" />
                  <XAxis type="number" allowDecimals={false} tick={{ fontSize: 12 }} />
                  <YAxis type="category" dataKey="name" tick={{ fontSize: 12 }} width={90} />
                  <Tooltip />
                  <Bar dataKey="count" fill="#0f7f76" radius={[0, 3, 3, 0]} />
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
                  <CartesianGrid vertical={false} stroke="#e5ddd0" />
                  <XAxis dataKey="day" tick={{ fontSize: 11 }} tickFormatter={(d: string) => d.slice(5)} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 12 }} />
                  <Tooltip />
                  <Bar dataKey="count" fill="#9a5a07" radius={[3, 3, 0, 0]} />
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
        <Card title="Investigations by status" actions={<Link className="text-sm text-teal-700 hover:underline" href="/app/investigations">All runs</Link>}>
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
