"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button, Card, Empty, ErrorState, Field, Input, Mono, Notice, PageHeader, Select, Skeleton, StatusBadge, useToast } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { useMe } from "@/lib/session";
import type { Account } from "@/lib/types";

interface Conn { id: string; kind: string; name: string; status: string; config: Record<string, unknown>; last_success_at: string | null; last_error: string | null; last_error_at: string | null; created_at: string }
interface Receipt { id: string; external_event_id: string; status: string; reason: string | null; ticket_id: string | null; received_at: string }

function Receipts({ id }: { id: string }) {
  const q = useQuery({ queryKey: ["receipts", id], queryFn: () => api.get<Receipt[]>(`/integrations/${id}/receipts`) });
  if (q.isLoading) return <Skeleton />;
  if (q.error) return <ErrorState error={q.error} />;
  if (!q.data!.length) return <p className="text-sm text-muted">No deliveries received yet.</p>;
  return (
    <ul className="divide-y divide-line text-sm">{q.data!.map((r) => (
      <li key={r.id} className="flex flex-wrap items-center gap-2 py-1.5"><StatusBadge status={r.status} /><Mono>{r.external_event_id}</Mono><span className="text-muted">{fmtDate(r.received_at)}</span>{r.reason ? <span className="w-full text-[13px] text-danger-700">{r.reason}</span> : null}</li>
    ))}</ul>
  );
}

export function IntegrationsPage() {
  const me = useMe();
  const qc = useQueryClient();
  const toast = useToast();
  const isAdmin = me.data?.role === "admin";
  const conns = useQuery({ queryKey: ["connections"], queryFn: () => api.get<Conn[]>("/integrations"), enabled: isAdmin });
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: () => api.get<Account[]>("/accounts"), enabled: isAdmin });
  const [name, setName] = useState("");
  const [ref, setRef] = useState("");
  const [acct, setAcct] = useState("");
  const [secret, setSecret] = useState<{ endpoint?: string; signing_secret: string } | null>(null);
  const create = useMutation<{ endpoint: string; signing_secret: string }, ApiError>({
    mutationFn: () => api.post("/integrations/webhooks", { name, account_map: { [ref]: acct } }),
    onSuccess: (r) => { setSecret(r); qc.invalidateQueries({ queryKey: ["connections"] }); },
  });
  const toggle = useMutation<unknown, ApiError, { id: string; action: string }>({
    mutationFn: ({ id, action }) => api.post(`/integrations/${id}/${action}`),
    onSuccess: () => { toast("Connection updated"); qc.invalidateQueries({ queryKey: ["connections"] }); },
  });
  if (!isAdmin) return <Empty title="Integrations are managed by an admin" />;
  return (
    <div>
      <PageHeader title="Integrations" subtitle="Where tickets come from and where approved handoffs can go. Status reflects real deliveries only." />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="flex flex-col gap-4">
          {conns.isLoading ? <Skeleton /> : conns.error ? <ErrorState error={conns.error} /> : conns.data!.length === 0 ? (
            <Empty title="No connections yet">The customer portal and staff entry work without any connection. Add an inbound webhook to receive tickets from another system.</Empty>
          ) : conns.data!.map((c) => (
            <Card key={c.id} title={<span className="flex items-center gap-2">{c.name}<StatusBadge status={c.status} /></span>}
              actions={<Button size="sm" onClick={() => toggle.mutate({ id: c.id, action: c.status === "disconnected" ? "enable" : "disable" })}>{c.status === "disconnected" ? "Enable" : "Disable"}</Button>}>
              <p className="text-sm text-muted">{c.kind === "inbound_webhook" ? "Inbound webhook" : "GitHub issues"} · added {fmtDate(c.created_at)}</p>
              <p className="mt-1 text-sm">Last successful delivery: {c.last_success_at ? fmtDate(c.last_success_at) : "never"}</p>
              {c.last_error ? <p className="text-sm text-danger-700">Last error ({fmtDate(c.last_error_at)}): {c.last_error}</p> : null}
              {c.kind === "inbound_webhook" ? <p className="mt-1 text-[13px] text-muted">Endpoint: <Mono>/api/ingest/webhooks/{c.id}</Mono></p> : null}
              <details className="mt-3"><summary className="cursor-pointer text-sm font-medium">Recent deliveries</summary><div className="mt-2"><Receipts id={c.id} /></div></details>
            </Card>
          ))}
        </div>
        <Card title="Add an inbound webhook">
          <form className="flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
            <Field id="cname" label="Name"><Input id="cname" value={name} onChange={(e) => setName(e.target.value)} placeholder="Helpdesk sync" /></Field>
            <Field id="cref" label="External account reference" hint="The account identifier the other system will send as account_ref."><Input id="cref" value={ref} onChange={(e) => setRef(e.target.value)} /></Field>
            <Field id="cacct" label="Maps to customer account">
              <Select id="cacct" value={acct} onChange={(e) => setAcct(e.target.value)}><option value="">Choose…</option>{accounts.data?.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</Select>
            </Field>
            <Button type="submit" variant="primary" disabled={!name || !ref || !acct} busy={create.isPending}>Create connection</Button>
            {create.error ? <Notice tone="danger">{create.error.detail}</Notice> : null}
            {secret ? (
              <Notice tone="warn" title="Copy the signing secret now; it is shown only once">
                <p className="mt-1">Secret: <Mono>{secret.signing_secret}</Mono></p>
                <p className="mt-1">Sign <Mono>{"<unix timestamp>.<raw body>"}</Mono> with HMAC-SHA256 and send <Mono>X-RelayOps-Timestamp</Mono> and <Mono>X-RelayOps-Signature: sha256=…</Mono>.</p>
              </Notice>
            ) : null}
          </form>
        </Card>
      </div>
    </div>
  );
}
