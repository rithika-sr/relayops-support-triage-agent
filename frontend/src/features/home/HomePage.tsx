"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ButtonLink, Card, Empty, ErrorState, PageHeader, Skeleton, Stat, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { relative } from "@/lib/format";
import { useMe } from "@/lib/session";
import type { Paged, RunSummary, Ticket } from "@/lib/types";
import { TargetBadge } from "@/features/tickets/TargetBadge";

interface Home {
  as_of: string;
  queues: { key: string; label: string; count: number; href: string }[];
  failed_runs: number;
}

function QueuePreview({ title, query, empty }: { title: string; query: string; empty: string }) {
  const q = useQuery({ queryKey: ["tickets", "home", query], queryFn: () => api.get<Paged<Ticket>>(`/tickets?${query}&page_size=5`) });
  return (
    <Card title={title} actions={<Link className="text-sm font-medium text-accent-700 hover:underline" href={`/app/inbox?${query}`}>View all</Link>} padded={false}>
      {q.isLoading ? <div className="p-5"><Skeleton /></div> : q.error ? <div className="p-5"><ErrorState error={q.error} /></div> : q.data!.items.length === 0 ? (
        <p className="px-5 py-6 text-sm text-muted">{empty}</p>
      ) : (
        <ul className="divide-y divide-line">
          {q.data!.items.map((t) => (
            <li key={t.id}>
              <Link href={`/app/tickets/${t.id}`} className="flex flex-col gap-1 px-5 py-3 hover:bg-sunken sm:flex-row sm:items-center sm:justify-between">
                <span className="min-w-0">
                  <span className="block truncate font-medium">{t.subject}</span>
                  <span className="text-[13px] text-muted">{t.account_name} · updated {relative(t.updated_at)}</span>
                </span>
                <span className="flex shrink-0 items-center gap-2"><StatusBadge status={t.priority} /><TargetBadge target={t.target} /></span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export function HomePage() {
  const me = useMe();
  const home = useQuery({ queryKey: ["home"], queryFn: () => api.get<Home>("/home"), refetchInterval: 30_000 });
  const failed = useQuery({ queryKey: ["runs", "failed"], queryFn: () => api.get<{ items: RunSummary[] }>("/investigations?status=failed&mode=live") });
  const total = home.data?.queues.reduce((n, q) => n + q.count, 0) ?? 0;
  return (
    <div>
      <PageHeader title={`Good to see you, ${me.data?.name.split(" ")[0] ?? ""}`} subtitle="What needs attention now. Every number opens the tickets behind it."
        actions={<ButtonLink href="/app/inbox" variant="primary">Open inbox</ButtonLink>} />
      {home.isLoading ? <Skeleton lines={2} /> : home.error ? <ErrorState error={home.error} retry={home.refetch} /> : (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          {home.data!.queues.map((q) => (
            <Stat key={q.key} label={q.label} value={q.count} href={q.href}
              tone={q.key === "breached" && q.count ? "danger" : q.key === "review" && q.count ? "warn" : undefined} />
          ))}
        </div>
      )}
      {home.data && total === 0 ? (
        <div className="mt-6">
          <Empty title="Nothing needs attention" action={<ButtonLink href="/app/settings">Set up channels and knowledge</ButtonLink>}>
            No open tickets yet. Tickets arrive from the customer portal, staff entry, imports, or a configured webhook.
          </Empty>
        </div>
      ) : (
        <div className="mt-6 grid gap-5 xl:grid-cols-2">
          <QueuePreview title="Drafts awaiting your review" query="queue=review&sort=due" empty="No drafts are waiting for review." />
          <QueuePreview title="Overdue or due soon" query="queue=breached&sort=due" empty="No first responses are overdue." />
          <QueuePreview title="Assigned to me" query="queue=open&assignee=me&sort=due" empty="Nothing is assigned to you." />
          <QueuePreview title="Open and unassigned" query="queue=open&assignee=none&sort=priority" empty="Every open ticket has an owner." />
        </div>
      )}
      {failed.data?.items.length ? (
        <div className="mt-6">
          <Card title="Investigations that need a retry">
            <ul className="text-sm">
              {failed.data.items.slice(0, 5).map((r) => (
                <li key={r.id} className="flex items-center justify-between gap-2 py-1">
                  <Link className="text-accent-700 hover:underline" href={`/app/investigations/${r.id}`}>{r.ticket_subject}</Link>
                  <span className="truncate text-[13px] text-muted">{r.error}</span>
                </li>
              ))}
            </ul>
          </Card>
        </div>
      ) : null}
    </div>
  );
}
