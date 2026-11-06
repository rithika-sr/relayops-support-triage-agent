"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, Button, Card, Empty, ErrorState, Input, PageHeader, Select, Skeleton, StatusBadge, Tabs, useToast } from "@/components/ui";
import { api, ApiError, qs } from "@/lib/api";
import { relative } from "@/lib/format";
import type { Account, Paged, Ticket } from "@/lib/types";
import { COMPONENTS, NewTicketForm } from "@/features/portal/NewTicketForm";
import { TargetBadge } from "./TargetBadge";

type Row = Ticket & { preview?: string | null; assignee?: { id: string; name: string } | null };
interface View { id: string; name: string; query: string }
interface Staff { id: string; name: string; role: string }

const QUEUES = [
  { id: "", label: "All" },
  { id: "open", label: "Open" },
  { id: "review", label: "Needs review" },
  { id: "breached", label: "Overdue" },
  { id: "due_soon", label: "Due soon" },
];
const FILTER_KEYS = ["q", "queue", "status", "priority", "account_id", "component", "assignee", "sort"];

export function InboxPage() {
  const params = useSearchParams();
  const router = useRouter();
  const path = usePathname();
  const qc = useQueryClient();
  const toast = useToast();
  const [creating, setCreating] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const f = Object.fromEntries(FILTER_KEYS.map((k) => [k, params.get(k) ?? ""])) as Record<string, string>;
  const page = Number(params.get("page") ?? 1);
  const setFilter = (k: string, v: string) => {
    const next = new URLSearchParams(params.toString());
    if (v) next.set(k, v); else next.delete(k);
    if (k !== "page") next.delete("page");
    setSelected(new Set());
    router.replace(`${path}?${next.toString()}`);
  };
  const query = { ...f, sort: f.sort || "newest", page, page_size: 25 };
  const tickets = useQuery({ queryKey: ["tickets", query], queryFn: () => api.get<Paged<Row>>(`/tickets${qs(query)}`), refetchInterval: 20_000 });
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: () => api.get<Account[]>("/accounts") });
  const staff = useQuery({ queryKey: ["staff"], queryFn: () => api.get<Staff[]>("/staff") });
  const views = useQuery({ queryKey: ["views"], queryFn: () => api.get<View[]>("/views") });
  const saveView = useMutation<View, ApiError, string>({
    mutationFn: (name) => api.post("/views", { name, query: params.toString() }),
    onSuccess: (v) => { qc.invalidateQueries({ queryKey: ["views"] }); toast(`Saved view “${v.name}”`); },
  });
  const bulk = useMutation<{ updated: number; results: Record<string, string> }, ApiError, Record<string, string | null>>({
    mutationFn: (changes) => api.post("/tickets/bulk", { ticket_ids: [...selected], changes }),
    onSuccess: (r) => {
      const skipped = Object.values(r.results).filter((v) => v !== "updated").length;
      toast(`Updated ${r.updated} ticket${r.updated === 1 ? "" : "s"}${skipped ? `; ${skipped} skipped` : ""}`, skipped ? "warn" : "ok");
      setSelected(new Set());
      qc.invalidateQueries({ queryKey: ["tickets"] });
    },
    onError: (e) => toast(e.detail, "danger"),
  });
  const rows = tickets.data?.items ?? [];
  const pages = tickets.data ? Math.max(1, Math.ceil(tickets.data.total / 25)) : 1;
  const toggle = (id: string) => setSelected((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const hasFilters = FILTER_KEYS.some((k) => k !== "sort" && f[k]);

  return (
    <div>
      <PageHeader title="Inbox" subtitle="Response targets follow each ticket's service calendar."
        actions={<>
          <a className="inline-flex items-center rounded-md border border-line-strong bg-card px-3.5 py-2 text-sm font-medium hover:bg-sunken" href={`/api/tickets/export.csv${qs({ status: f.status, account_id: f.account_id })}`}>Export CSV</a>
          <Button variant="primary" onClick={() => setCreating((c) => !c)} aria-expanded={creating}>{creating ? "Close form" : "New ticket"}</Button>
        </>} />
      {creating ? (
        <Card title="New ticket on behalf of a customer" className="mb-5">
          <NewTicketForm accounts={accounts.data} onCreated={(t) => router.push(`/app/tickets/${t.id}`)} />
        </Card>
      ) : null}

      <Tabs label="Queues" value={f.queue} onChange={(id) => setFilter("queue", id)} tabs={QUEUES} />

      <div className="mt-4 flex flex-wrap items-center gap-2">
        {views.data?.map((v) => (
          <Link key={v.id} href={`${path}?${v.query}`} className="rounded-full border border-line-strong bg-card px-3 py-1 text-[13px] hover:border-accent-600">{v.name}</Link>
        ))}
        {hasFilters ? (
          <Button size="sm" variant="ghost" onClick={() => { const name = window.prompt("Name this view"); if (name) saveView.mutate(name); }}>Save this view</Button>
        ) : null}
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-6" role="search">
        <label className="sr-only" htmlFor="q">Search</label>
        <Input id="q" className="lg:col-span-2" placeholder="Search subject, error code, or #number" defaultValue={f.q}
          onKeyDown={(e) => { if (e.key === "Enter") setFilter("q", (e.target as HTMLInputElement).value); }} />
        <Select aria-label="Assignee" value={f.assignee} onChange={(e) => setFilter("assignee", e.target.value)}>
          <option value="">Anyone</option><option value="me">Assigned to me</option><option value="none">Unassigned</option>
          {staff.data?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </Select>
        <Select aria-label="Account" value={f.account_id} onChange={(e) => setFilter("account_id", e.target.value)}>
          <option value="">Any account</option>
          {accounts.data?.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
        </Select>
        <Select aria-label="Component" value={f.component} onChange={(e) => setFilter("component", e.target.value)}>
          <option value="">Any area</option>{COMPONENTS.map((c) => <option key={c} value={c}>{c}</option>)}
        </Select>
        <Select aria-label="Sort" value={f.sort || "newest"} onChange={(e) => setFilter("sort", e.target.value)}>
          <option value="newest">Newest first</option><option value="due">Response due first</option>
          <option value="priority">Highest priority</option><option value="updated">Recently updated</option><option value="oldest">Oldest first</option>
        </Select>
      </div>

      {selected.size ? (
        <div className="sticky top-0 z-10 mt-3 flex flex-wrap items-center gap-2 rounded-lg border border-accent-100 bg-accent-50 px-3 py-2 text-sm">
          <span className="font-medium">{selected.size} selected</span>
          <Select aria-label="Assign selected" className="w-auto" value="" onChange={(e) => e.target.value && bulk.mutate({ assignee_user_id: e.target.value === "none" ? null : e.target.value })}>
            <option value="">Assign to…</option><option value="none">Nobody</option>
            {staff.data?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </Select>
          <Select aria-label="Set priority" className="w-auto" value="" onChange={(e) => e.target.value && bulk.mutate({ priority: e.target.value })}>
            <option value="">Set priority…</option>{["urgent", "high", "normal", "low"].map((p) => <option key={p} value={p}>{p}</option>)}
          </Select>
          <Select aria-label="Set status" className="w-auto" value="" onChange={(e) => e.target.value && bulk.mutate({ status: e.target.value })}>
            <option value="">Set status…</option>{["open", "pending_customer", "resolved", "closed"].map((p) => <option key={p} value={p}>{p.replace("_", " ")}</option>)}
          </Select>
          <span className="text-[13px] text-muted">Replies to customers are never sent in bulk.</span>
          <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>Clear</Button>
        </div>
      ) : null}

      <div className="mt-4">
        {tickets.isLoading ? <Card><Skeleton lines={5} /></Card> : tickets.error ? <ErrorState error={tickets.error} retry={tickets.refetch} /> : rows.length === 0 ? (
          <Empty title={hasFilters ? "No tickets match these filters" : "No tickets yet"}>
            {hasFilters ? "Try another queue or clear filters." : "Tickets arrive from the customer portal, staff entry, imports, and configured webhooks."}
          </Empty>
        ) : (
          <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-card shadow-[var(--shadow-raised)]" aria-label="Tickets">
            {rows.map((t) => (
              <li key={t.id} className="flex gap-3 px-4 py-3 hover:bg-sunken">
                <input type="checkbox" className="mt-1 size-4 shrink-0" aria-label={`Select #${t.number}`} checked={selected.has(t.id)} onChange={() => toggle(t.id)} />
                <Link href={`/app/tickets/${t.id}`} className="min-w-0 flex-1">
                  <div className="flex flex-col gap-1 md:flex-row md:items-start md:justify-between md:gap-4">
                    <div className="min-w-0">
                      <p className="truncate font-medium">{t.subject}</p>
                      <p className="truncate text-[13px] text-muted">{t.account_name} · #{t.number}{t.component ? ` · ${t.component}` : ""}{t.preview ? ` — ${t.preview}` : ""}</p>
                    </div>
                    <div className="flex shrink-0 flex-wrap items-center gap-1.5 md:justify-end">
                      {t.restricted ? <Badge tone="danger">restricted</Badge> : null}
                      <StatusBadge status={t.status} />
                      {t.priority !== "normal" ? <StatusBadge status={t.priority} /> : null}
                      <TargetBadge target={t.target} />
                    </div>
                  </div>
                  <p className="mt-1 text-xs text-subtle">{t.assignee ? `Assigned to ${t.assignee.name}` : "Unassigned"} · updated {relative(t.updated_at)}</p>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
      {tickets.data && pages > 1 ? (
        <nav className="mt-3 flex items-center justify-between text-sm" aria-label="Pagination">
          <span className="text-muted">{tickets.data.total} tickets · page {page} of {pages}</span>
          <span className="flex gap-2">
            <Button size="sm" disabled={page <= 1} onClick={() => setFilter("page", String(page - 1))}>Previous</Button>
            <Button size="sm" disabled={page >= pages} onClick={() => setFilter("page", String(page + 1))}>Next</Button>
          </span>
        </nav>
      ) : null}
    </div>
  );
}
