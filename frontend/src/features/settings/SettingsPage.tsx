"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, Button, Card, ErrorState, Input, Loading, Mono, Notice, PageHeader, Select } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { fmtDate, label } from "@/lib/format";
import { useMe } from "@/lib/session";
import type { Account } from "@/lib/types";

interface Health { database: string; pgvector?: string; provider: string; ollama: { reachable: boolean; chat_model?: string; chat_model_present?: boolean; embed_model?: string; embed_model_present?: boolean; installed?: string[]; error?: string; note?: string }; embedding_index: { index_models: Record<string, number>; provider_model: string; compatible: boolean }; embedding_dim: number; budgets: Record<string, number> }

function Admin() {
  const qc = useQueryClient();
  const members = useQuery({ queryKey: ["members"], queryFn: () => api.get<{ email: string; name: string; role: string; customer_account: string | null }[]>("/settings/members") });
  const tokens = useQuery({ queryKey: ["tokens"], queryFn: () => api.get<{ id: string; name: string; scopes: string[]; created_at: string; revoked_at: string | null; last_used_at: string | null }[]>("/settings/tokens") });
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: () => api.get<Account[]>("/accounts") });
  const [inv, setInv] = useState({ email: "", customer_account_id: "" });
  const [tokName, setTokName] = useState("");
  const invite = useMutation<{ accept_url: string; note: string }, ApiError>({ mutationFn: () => api.post("/settings/invitations", inv), onSuccess: () => qc.invalidateQueries({ queryKey: ["members"] }) });
  const mkTok = useMutation<{ token: string; note: string }, ApiError>({ mutationFn: () => api.post("/settings/tokens", { name: tokName, scopes: ["mcp:read"] }), onSuccess: () => qc.invalidateQueries({ queryKey: ["tokens"] }) });
  const revoke = useMutation<unknown, ApiError, string>({ mutationFn: (id) => api.post(`/settings/tokens/${id}/revoke`), onSuccess: () => qc.invalidateQueries({ queryKey: ["tokens"] }) });
  return (
    <>
      <AccountsCard accounts={accounts.data ?? []} />
      <Card title="Members">
        {members.isLoading ? <Loading /> : members.error ? <ErrorState error={members.error} /> : (
          <ul className="text-sm">{members.data!.map((m) => <li key={m.email}>{m.name} · {m.email} <Badge>{m.role}</Badge>{m.customer_account ? <span className="text-xs text-muted"> {m.customer_account}</span> : null}</li>)}</ul>
        )}
        <form className="mt-3 grid gap-2 sm:grid-cols-[1fr_1fr_auto]" onSubmit={(e) => { e.preventDefault(); invite.mutate(); }}>
          <Input aria-label="Invitee email" placeholder="customer@example.com" value={inv.email} onChange={(e) => setInv({ ...inv, email: e.target.value })} />
          <Select aria-label="Customer account" value={inv.customer_account_id} onChange={(e) => setInv({ ...inv, customer_account_id: e.target.value })}><option value="">Customer account…</option>{accounts.data?.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</Select>
          <Button type="submit" busy={invite.isPending} disabled={!inv.email || !inv.customer_account_id}>Create customer invitation</Button>
        </form>
        {invite.data ? <Notice tone="ok">Invitation link (shown once; RelayOps does not send email): <Mono>{invite.data.accept_url}</Mono></Notice> : null}
        {invite.error ? <Notice tone="danger">{invite.error.detail}</Notice> : null}
      </Card>
      <Card title="Read-only API tokens (MCP scope)">
        <Notice>Use a token as a bearer credential for the read-only MCP endpoint at <code className="font-mono">/mcp/</code> (streamable HTTP). It can search knowledge and read tickets, investigations, and artifacts in this organization. It cannot change anything, and every REST endpoint rejects it. Revoking a token stops it on the next request.</Notice>
        <ul className="mt-2 text-sm">{tokens.data?.map((t) => <li key={t.id} className="flex items-center gap-2">{t.name} <Badge>{t.scopes.join(",")}</Badge><span className="text-xs text-muted">{fmtDate(t.created_at)}</span>{t.revoked_at ? <Badge tone="danger">revoked</Badge> : <Button variant="danger" onClick={() => revoke.mutate(t.id)}>Revoke</Button>}</li>)}</ul>
        <form className="mt-2 flex gap-2" onSubmit={(e) => { e.preventDefault(); mkTok.mutate(); }}><Input aria-label="Token name" placeholder="token name" value={tokName} onChange={(e) => setTokName(e.target.value)} /><Button type="submit" disabled={!tokName} busy={mkTok.isPending}>Create</Button></form>
        {mkTok.data ? <Notice tone="ok">Token (shown once): <Mono>{mkTok.data.token}</Mono></Notice> : null}
      </Card>
    </>
  );
}

export function SettingsPage() {
  const me = useMe();
  const health = useQuery({ queryKey: ["health"], queryFn: () => api.get<Health>("/settings/health") });
  const policy = useQuery({ queryKey: ["policy"], queryFn: () => api.get<{ policy_version: string; basis: string; first_response_hours: Record<string, Record<string, number>>; entitlements: Record<string, Record<string, boolean | number>> }>("/settings/policy") });
  const conn = useQuery({ queryKey: ["connectors"], queryFn: () => api.get<{ action_mode: string; adapters: { name: string; enabled: boolean; description: string }[] }>("/settings/connectors") });
  const h = health.data;
  return (
    <div className="flex flex-col gap-4">
      <PageHeader title="Settings" subtitle={me.data ? `${me.data.name} · ${me.data.email} · ${me.data.role} in ${me.data.organization.name}` : undefined} />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Model and dependency health" actions={<Button variant="ghost" onClick={() => health.refetch()}>Recheck</Button>}>
          {health.isLoading ? <Loading /> : health.error ? <ErrorState error={health.error} /> : (
            <dl className="grid grid-cols-[10rem_1fr] gap-y-1 text-sm">
              <dt className="text-muted">Database</dt><dd>{h!.database} {h!.pgvector ? `(pgvector ${h!.pgvector})` : ""}</dd>
              <dt className="text-muted">Provider</dt><dd>{h!.provider === "fixture" ? <Badge tone="danger">fixture (tests only)</Badge> : <Badge tone="accent">ollama (local)</Badge>}</dd>
              <dt className="text-muted">Ollama</dt><dd>{h!.ollama.reachable ? <Badge tone="ok">reachable</Badge> : <Badge tone="danger">unavailable</Badge>} {h!.ollama.error ?? h!.ollama.note ?? ""}</dd>
              <dt className="text-muted">Chat model</dt><dd>{h!.ollama.chat_model ?? "—"} {h!.ollama.chat_model_present === false ? <Badge tone="danger">not installed</Badge> : null}</dd>
              <dt className="text-muted">Embedding model</dt><dd>{h!.ollama.embed_model ?? "—"} ({h!.embedding_dim}-d) {h!.ollama.embed_model_present === false ? <Badge tone="danger">not installed</Badge> : null}</dd>
              <dt className="text-muted">Index</dt><dd>{h!.embedding_index.compatible ? <Badge tone="ok">compatible</Badge> : <Badge tone="danger">model mismatch</Badge>} {Object.entries(h!.embedding_index.index_models).map(([m, n]) => `${m}: ${n} chunks`).join(", ")}</dd>
              <dt className="text-muted">Budgets</dt><dd className="text-xs">{Object.entries(h!.budgets).map(([k, v]) => `${label(k)} ${v}`).join(" · ")}</dd>
            </dl>
          )}
        </Card>
        <Card title="Connector mode">
          {conn.isLoading ? <Loading /> : conn.error ? <ErrorState error={conn.error} /> : (
            <ul className="flex flex-col gap-2 text-sm">{conn.data!.adapters.map((a) => <li key={a.name}><span className="font-medium">{a.name}</span> {a.enabled ? <Badge tone="ok">enabled</Badge> : <Badge>disabled</Badge>}<p className="text-xs text-muted">{a.description}</p></li>)}</ul>
          )}
        </Card>
      </div>
      <Card title={`Support policy ${policy.data?.policy_version ?? ""}`}>
        {policy.isLoading ? <Loading /> : policy.error ? <ErrorState error={policy.error} /> : (
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="overflow-x-auto"><p className="mb-1 text-xs text-muted">First-response targets, {policy.data!.basis}</p><table className="w-full text-sm"><thead className="text-left text-xs text-muted"><tr><th>Plan</th><th>Urgent</th><th>High</th><th>Normal</th><th>Low</th></tr></thead><tbody>{Object.entries(policy.data!.first_response_hours).map(([plan, t]) => <tr key={plan} className="border-t border-line"><td className="py-1">{plan}</td><td>{t.urgent}h</td><td>{t.high}h</td><td>{t.normal}h</td><td>{t.low}h</td></tr>)}</tbody></table></div>
            <div className="overflow-x-auto"><p className="mb-1 text-xs text-muted">Entitlements</p><table className="w-full text-sm"><thead className="text-left text-xs text-muted"><tr><th>Plan</th><th>SSO</th><th>SCIM</th><th>Webhooks</th><th>Export rows</th></tr></thead><tbody>{Object.entries(policy.data!.entitlements).map(([plan, e]) => <tr key={plan} className="border-t border-line"><td className="py-1">{plan}</td><td>{e.sso ? "yes" : "no"}</td><td>{e.scim ? "yes" : "no"}</td><td>{e.webhooks ? "yes" : "no"}</td><td>{Number(e.export_row_limit).toLocaleString()}</td></tr>)}</tbody></table></div>
          </div>
        )}
        <p className="mt-2 text-xs text-muted">Policy values are versioned in code (relayops.domain.policies). Changing them ships as a new policy version so pending approvals bound to the old version go stale.</p>
      </Card>
      {me.data?.role === "admin" ? <Admin /> : <Notice>Organization membership, invitations, and tokens are managed by an admin.</Notice>}
    </div>
  );
}

function AccountsCard({ accounts }: { accounts: Account[] }) {
  const qc = useQueryClient();
  const [f, setF] = useState({ name: "", plan: "team", product_version: "" });
  const add = useMutation<Account, ApiError>({
    mutationFn: () => api.post("/settings/accounts", f),
    onSuccess: () => { setF({ ...f, name: "", product_version: "" }); qc.invalidateQueries({ queryKey: ["accounts"] }); },
  });
  return (
    <Card title="Customer accounts">
      {accounts.length ? (
        <ul className="text-sm">{accounts.map((a) => <li key={a.id}>{a.name} <Badge>{a.plan}</Badge> <span className="text-xs text-muted">version {a.product_version}</span></li>)}</ul>
      ) : <p className="text-sm text-muted">No customer accounts yet. Add one to invite its users, file tickets for it, or map imports and webhooks to it.</p>}
      <form className="mt-3 grid gap-2 sm:grid-cols-[1fr_9rem_8rem_auto]" onSubmit={(e) => { e.preventDefault(); add.mutate(); }}>
        <Input aria-label="Account name" placeholder="Customer company" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
        <Select aria-label="Plan" value={f.plan} onChange={(e) => setF({ ...f, plan: e.target.value })}>{["starter", "team", "business", "enterprise"].map((pl) => <option key={pl}>{pl}</option>)}</Select>
        <Input aria-label="Product version" placeholder="2.5" value={f.product_version} onChange={(e) => setF({ ...f, product_version: e.target.value })} />
        <Button type="submit" busy={add.isPending} disabled={f.name.trim().length < 2 || !f.product_version}>Add account</Button>
      </form>
      {add.error ? <Notice tone="danger">{add.error.detail}</Notice> : null}
    </Card>
  );
}
