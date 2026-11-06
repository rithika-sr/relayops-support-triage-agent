"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, Button, Card, Empty, ErrorState, Input, Loading, PageHeader, Select, StatusBadge } from "@/components/ui";
import { api, qs } from "@/lib/api";
import { relative } from "@/lib/format";
import type { Account, Paged, Ticket } from "@/lib/types";
import { COMPONENTS, NewTicketForm } from "@/features/portal/NewTicketForm";
import { TargetBadge } from "./TargetBadge";

export function InboxPage() {
  const params = useSearchParams();
  const router = useRouter();
  const path = usePathname();
  const [creating, setCreating] = useState(false);
  const filters = {
    q: params.get("q") ?? "",
    status: params.get("status") ?? "",
    priority: params.get("priority") ?? "",
    account_id: params.get("account_id") ?? "",
    component: params.get("component") ?? "",
    page: Number(params.get("page") ?? 1),
  };
  const setFilter = (k: string, v: string) => {
    const next = new URLSearchParams(params.toString());
    if (v) next.set(k, v); else next.delete(k);
    if (k !== "page") next.delete("page");
    router.replace(`${path}?${next.toString()}`);
  };
  const tickets = useQuery({
    queryKey: ["tickets", filters],
    queryFn: () => api.get<Paged<Ticket>>(`/tickets${qs({ ...filters, page_size: 25 })}`),
    refetchInterval: 20_000,
  });
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: () => api.get<Account[]>("/accounts") });
  const pages = tickets.data ? Math.max(1, Math.ceil(tickets.data.total / 25)) : 1;

  return (
    <div>
      <PageHeader
        title="Inbox"
        subtitle="Response targets are 24/7 elapsed hours from the current policy."
        actions={
          <>
            <a className="inline-flex items-center rounded-md border border-line-strong bg-card px-3 py-1.5 text-sm font-medium hover:bg-paper" href={`/api/tickets/export.csv${qs({ status: filters.status, account_id: filters.account_id })}`}>Export CSV</a>
            <Button variant="primary" onClick={() => setCreating((c) => !c)} aria-expanded={creating}>{creating ? "Close" : "New ticket"}</Button>
          </>
        }
      />
      {creating ? (
        <Card title="New ticket on behalf of a customer" className="mb-4">
          <NewTicketForm accounts={accounts.data} onCreated={(t) => router.push(`/app/tickets/${t.id}`)} />
        </Card>
      ) : null}
      <div className="mb-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-5" role="search">
        <label className="sr-only" htmlFor="q">Search</label>
        <Input id="q" placeholder="Search subject, error, or #number" defaultValue={filters.q} onKeyDown={(e) => { if (e.key === "Enter") setFilter("q", (e.target as HTMLInputElement).value); }} />
        <Select aria-label="Status" value={filters.status} onChange={(e) => setFilter("status", e.target.value)}>
          <option value="">Any status</option>
          {["open", "pending_review", "pending_customer", "resolved", "closed"].map((s) => <option key={s} value={s}>{s.replace("_", " ")}</option>)}
        </Select>
        <Select aria-label="Priority" value={filters.priority} onChange={(e) => setFilter("priority", e.target.value)}>
          <option value="">Any priority</option>
          {["urgent", "high", "normal", "low"].map((s) => <option key={s} value={s}>{s}</option>)}
        </Select>
        <Select aria-label="Account" value={filters.account_id} onChange={(e) => setFilter("account_id", e.target.value)}>
          <option value="">Any account</option>
          {accounts.data?.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
        </Select>
        <Select aria-label="Component" value={filters.component} onChange={(e) => setFilter("component", e.target.value)}>
          <option value="">Any component</option>
          {COMPONENTS.map((c) => <option key={c} value={c}>{c}</option>)}
        </Select>
      </div>
      {tickets.isLoading ? <Loading /> : tickets.error ? <ErrorState error={tickets.error} retry={tickets.refetch} /> : tickets.data!.items.length === 0 ? (
        <Empty title="No tickets match these filters" />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-line bg-card">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="border-b border-line bg-paper text-left text-xs text-muted uppercase">
              <tr>
                <th className="px-3 py-2 font-medium">Ticket</th>
                <th className="px-3 py-2 font-medium">Account</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Priority</th>
                <th className="px-3 py-2 font-medium">First response</th>
                <th className="px-3 py-2 font-medium">Updated</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {tickets.data!.items.map((t) => (
                <tr key={t.id} className="hover:bg-paper">
                  <td className="px-3 py-2">
                    <Link href={`/app/tickets/${t.id}`} className="font-medium text-text hover:text-teal-700">
                      <span className="text-muted">#{t.number}</span> {t.subject}
                    </Link>
                    <div className="mt-0.5 flex flex-wrap gap-1">
                      {t.component ? <Badge>{t.component}</Badge> : null}
                      {t.error_code ? <Badge>{t.error_code}</Badge> : null}
                      {t.restricted ? <Badge tone="danger">restricted</Badge> : null}
                    </div>
                  </td>
                  <td className="px-3 py-2">{t.account_name}</td>
                  <td className="px-3 py-2"><StatusBadge status={t.status} /></td>
                  <td className="px-3 py-2"><StatusBadge status={t.priority} /></td>
                  <td className="px-3 py-2"><TargetBadge target={t.target} /></td>
                  <td className="px-3 py-2 text-muted">{relative(t.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {tickets.data && pages > 1 ? (
        <nav className="mt-3 flex items-center justify-between text-sm" aria-label="Pagination">
          <span className="text-muted">{tickets.data.total} tickets · page {filters.page} of {pages}</span>
          <span className="flex gap-2">
            <Button disabled={filters.page <= 1} onClick={() => setFilter("page", String(filters.page - 1))}>Previous</Button>
            <Button disabled={filters.page >= pages} onClick={() => setFilter("page", String(filters.page + 1))}>Next</Button>
          </span>
        </nav>
      ) : null}
    </div>
  );
}
