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
  const check = useMutation<{ ok: boolean; status: string; error?: string; repository?: string }, ApiError, string>({
    mutationFn: (id) => api.post(`/integrations/${id}/test`),
    onSuccess: (r) => { toast(r.ok ? `Reached ${r.repository}` : `Check failed: ${r.error}`, r.ok ? undefined : "neutral"); qc.invalidateQueries({ queryKey: ["connections"] }); },
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
              actions={<span className="flex gap-2">
                {c.kind === "github_issues" ? <Button size="sm" busy={check.isPending && check.variables === c.id} onClick={() => check.mutate(c.id)}>Test connection</Button> : null}
                <Button size="sm" onClick={() => toggle.mutate({ id: c.id, action: c.status === "disconnected" ? "enable" : "disable" })}>{c.status === "disconnected" ? "Enable" : "Disable"}</Button>
              </span>}>
              <p className="text-sm text-muted">{c.kind === "inbound_webhook" ? "Inbound webhook" : "GitHub issues"} · added {fmtDate(c.created_at)}</p>
              <p className="mt-1 text-sm">Last successful delivery: {c.last_success_at ? fmtDate(c.last_success_at) : "never"}</p>
              {c.last_error ? <p className="text-sm text-danger-700">Last error ({fmtDate(c.last_error_at)}): {c.last_error}</p> : null}
              {c.kind === "inbound_webhook" ? <p className="mt-1 text-[13px] text-muted">Endpoint: <Mono>/api/ingest/webhooks/{c.id}</Mono></p> : null}
              {c.kind === "github_issues" ? <p className="mt-1 text-[13px] text-muted">Mirrors approved handoffs to <Mono>{String(c.config.repo)}</Mono> at <Mono>{String(c.config.base_url)}</Mono> (local test service).</p> : null}
              {c.kind === "inbound_webhook" ? <details className="mt-3"><summary className="cursor-pointer text-sm font-medium">Recent deliveries</summary><div className="mt-2"><Receipts id={c.id} /></div></details> : null}
            </Card>
          ))}
        </div>
        <div className="flex flex-col gap-5">
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
        <GitHubForm />
        </div>
      </div>
    </div>
  );
}

function GitHubForm() {
  const qc = useQueryClient();
  const [f, setF] = useState({ name: "", base_url: "http://127.0.0.1:", repo: "", token: "" });
  const create = useMutation<unknown, ApiError>({
    mutationFn: () => api.post("/integrations/github", f),
    onSuccess: () => { setF({ ...f, name: "", token: "" }); qc.invalidateQueries({ queryKey: ["connections"] }); },
  });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  return (
    <Card title="Mirror handoffs to a GitHub-compatible tracker">
      <Notice tone="warn">This release only connects to a loopback test service (localhost). Writing to github.com is a live external operation and needs a separately authorized setup; a token alone does not enable it.</Notice>
      <form className="mt-3 flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
        <Field id="gname" label="Name"><Input id="gname" value={f.name} onChange={set("name")} /></Field>
        <Field id="gurl" label="API base URL"><Input id="gurl" value={f.base_url} onChange={set("base_url")} /></Field>
        <Field id="grepo" label="Repository" hint="owner/name"><Input id="grepo" value={f.repo} onChange={set("repo")} /></Field>
        <Field id="gtok" label="Token" hint="Stored encrypted; never shown again."><Input id="gtok" type="password" autoComplete="off" value={f.token} onChange={set("token")} /></Field>
        <Button type="submit" disabled={!f.name || !f.repo || !f.token} busy={create.isPending}>Add connection</Button>
        {create.error ? <Notice tone="danger">{create.error.detail}</Notice> : null}
      </form>
    </Card>
  );
}
