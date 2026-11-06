"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Card, Empty, ErrorState, Loading, PageHeader, StatusBadge } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { useMe } from "@/lib/session";
import type { Doc, Incident, Paged, Ticket } from "@/lib/types";
import { GettingStarted } from "./GettingStarted";
import { NewTicketForm } from "./NewTicketForm";

export function PortalHome() {
  const router = useRouter();
  const me = useMe();
  const tickets = useQuery({ queryKey: ["tickets", "portal"], queryFn: () => api.get<Paged<Ticket>>("/tickets?page_size=50") });
  const incidents = useQuery({ queryKey: ["incidents", "public"], queryFn: () => api.get<Incident[]>("/incidents") });
  const docs = useQuery({ queryKey: ["knowledge", "public"], queryFn: () => api.get<Doc[]>("/knowledge") });
  const active = incidents.data?.filter((i) => i.status !== "resolved") ?? [];

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title="Support" subtitle={`${me.data?.customer_account?.name ?? ""} · replies from TaskFlow support appear here after review`} />
      {active.length ? (
        <div role="status" className="rounded-lg border border-warn-100 bg-warn-50 px-4 py-3 text-sm">
          {active.slice(0, 2).map((i) => (
            <p key={i.id}><span className="font-medium text-warn-700">{i.title}:</span> {i.public_summary}</p>
          ))}
          {active.length > 2 ? (
            <details className="mt-1">
              <summary className="cursor-pointer text-warn-700">{active.length - 2} more active incident{active.length - 2 === 1 ? "" : "s"}</summary>
              {active.slice(2).map((i) => (
                <p key={i.id} className="mt-1"><span className="font-medium text-warn-700">{i.title}:</span> {i.public_summary}</p>
              ))}
            </details>
          ) : null}
        </div>
      ) : null}
      <GettingStarted />
      <div className="grid gap-5 lg:grid-cols-5">
        <Card title="Your tickets" className="lg:col-span-3">
          {tickets.isLoading ? <Loading /> : tickets.error ? <ErrorState error={tickets.error} retry={tickets.refetch} /> : tickets.data!.items.length === 0 ? (
            <Empty title="No tickets yet">Use the form to tell us what is going on.</Empty>
          ) : (
            <ul className="divide-y divide-line">
              {tickets.data!.items.map((t) => (
                <li key={t.id}>
                  <Link href={`/portal/tickets/${t.id}`} className="flex items-center justify-between gap-3 py-2.5 hover:bg-paper">
                    <span className="min-w-0">
                      <span className="block truncate font-medium">{t.subject}</span>
                      <span className="text-xs text-muted">#{t.number} · {fmtDate(t.created_at)}</span>
                    </span>
                    <StatusBadge status={t.status === "pending_review" ? "open" : t.status} />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="New ticket" className="lg:col-span-2">
          <NewTicketForm onCreated={(t) => router.push(`/portal/tickets/${t.id}`)} />
        </Card>
      </div>
      <Card title="Help articles" actions={<Link className="text-sm text-accent-700 hover:underline" href="/portal/help">Search Help</Link>}>
        {docs.isLoading ? <Loading /> : docs.error ? <ErrorState error={docs.error} /> : (
          <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {docs.data!.filter((d) => d.status === "current").map((d) => (
              <li key={d.id} className="text-sm">
                <a className="text-accent-700 hover:underline" href={`/api/knowledge/${d.id}/versions/${d.current_version}/raw`}>{d.title}</a>
                <span className="ml-1 text-xs text-muted">{d.kind.replace("_", " ")}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
