"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, Button, Card, Empty, ErrorState, Field, Input, Loading, Mono, Notice, PageHeader, Select, StatusBadge } from "@/components/ui";
import { api, ApiError, qs } from "@/lib/api";
import { fmtDate, shortHash } from "@/lib/format";
import type { Account, Doc } from "@/lib/types";
import { COMPONENTS } from "@/features/portal/NewTicketForm";

interface DocDetail {
  document: Doc;
  versions: { id: string; version: number; content_hash: string; valid_from: string | null; valid_to: string | null; created_at: string; content?: string; source_filename: string | null }[];
}
interface Hit { chunk_id: string; slug: string; title: string; heading: string; kind: string; visibility: string; version: number; authority: number; score: number; text: string; ranks: Record<string, number> }

function Upload({ accounts }: { accounts?: Account[] }) {
  const qc = useQueryClient();
  const [f, setF] = useState({ slug: "", title: "", kind: "article", visibility: "public", component: "", product_versions: "", customer_account_id: "" });
  const [file, setFile] = useState<File | null>(null);
  const m = useMutation<{ changed: boolean; document: Doc }, ApiError>({
    mutationFn: () => {
      const fd = new FormData();
      Object.entries(f).forEach(([k, v]) => v && fd.append(k, v));
      if (file) fd.append("file", file);
      return api.post("/knowledge", fd);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["knowledge"] }),
  });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  return (
    <form className="grid gap-3 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); m.mutate(); }}>
      <Field id="kf" label="File (.md or .txt, UTF-8, ≤200 KB)"><Input id="kf" type="file" accept=".md,.markdown,.txt,text/markdown,text/plain" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></Field>
      <Field id="ks" label="Slug" hint="Re-using a slug creates a new version."><Input id="ks" value={f.slug} onChange={set("slug")} placeholder="exporting-projects" /></Field>
      <Field id="kt" label="Title"><Input id="kt" value={f.title} onChange={set("title")} /></Field>
      <Field id="kk" label="Kind"><Select id="kk" value={f.kind} onChange={set("kind")}>{["policy", "article", "runbook", "release_note", "historical_case"].map((k) => <option key={k}>{k}</option>)}</Select></Field>
      <Field id="kv" label="Visibility"><Select id="kv" value={f.visibility} onChange={set("visibility")}><option value="public">public (customers can read)</option><option value="internal">internal (staff and agent only)</option></Select></Field>
      <Field id="kc" label="Component"><Select id="kc" value={f.component} onChange={set("component")}><option value="">none</option>{COMPONENTS.map((c) => <option key={c}>{c}</option>)}</Select></Field>
      <Field id="kpv" label="Product versions" hint="Comma separated"><Input id="kpv" value={f.product_versions} onChange={set("product_versions")} placeholder="2.4, 2.5" /></Field>
      <Field id="ka" label="Account scope"><Select id="ka" value={f.customer_account_id} onChange={set("customer_account_id")}><option value="">Whole organization</option>{accounts?.map((a) => <option key={a.id} value={a.id}>{a.name} only</option>)}</Select></Field>
      <div className="sm:col-span-2 flex flex-wrap items-center gap-2">
        <Button variant="primary" type="submit" busy={m.isPending} disabled={!file || !f.slug || !f.title}>Ingest and embed</Button>
        {m.data ? <Notice tone="ok">{m.data.changed ? `Stored version ${m.data.document.current_version}.` : "Content unchanged; no new version."}</Notice> : null}
        {m.error ? <Notice tone="danger">{m.error.detail}</Notice> : null}
      </div>
    </form>
  );
}

function Inspector({ accounts }: { accounts?: Account[] }) {
  const [query, setQuery] = useState("Can we enable SSO on the Business plan?");
  const [mode, setMode] = useState("rrf");
  const [audience, setAudience] = useState("staff");
  const [account, setAccount] = useState("acct_northstar");
  const m = useMutation<{ results: Hit[]; mode: string; lexical_engine: string; dense_error?: string }, ApiError>({
    mutationFn: () => api.post("/knowledge/inspect", { query, mode, k: 6, audience, customer_account_id: account || null }),
  });
  return (
    <div className="flex flex-col gap-3">
      <form className="grid gap-2 sm:grid-cols-[1fr_auto_auto_auto_auto]" onSubmit={(e) => { e.preventDefault(); m.mutate(); }}>
        <Input aria-label="Query" value={query} onChange={(e) => setQuery(e.target.value)} />
        <Select aria-label="Mode" value={mode} onChange={(e) => setMode(e.target.value)}><option value="lexical">lexical</option><option value="dense">dense</option><option value="rrf">RRF</option></Select>
        <Select aria-label="Audience" value={audience} onChange={(e) => setAudience(e.target.value)}><option value="staff">staff view</option><option value="customer">customer view</option></Select>
        <Select aria-label="Account" value={account} onChange={(e) => setAccount(e.target.value)}><option value="">no account</option>{accounts?.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</Select>
        <Button type="submit" busy={m.isPending}>Search</Button>
      </form>
      <p className="text-xs text-muted">All modes share one authorization and currency filter. Lexical uses PostgreSQL ts_rank_cd (not BM25); dense uses exact cosine over local embeddings; scores include an authority boost (policy &gt; article &gt; historical case).</p>
      {m.error ? <ErrorState error={m.error} /> : null}
      {m.data?.dense_error ? <Notice tone="warn">Dense retrieval unavailable: {m.data.dense_error}</Notice> : null}
      {m.data ? (m.data.results.length === 0 ? <Empty title="No authorized current passages matched" /> : (
        <ol className="flex flex-col gap-2">
          {m.data.results.map((h, i) => (
            <li key={h.chunk_id} className="rounded-md border border-line bg-white px-3 py-2 text-sm">
              <div className="flex flex-wrap items-center gap-1"><span className="font-mono text-xs">{i + 1}.</span><span className="font-medium">{h.title}</span>{h.heading ? <span className="text-muted">/ {h.heading}</span> : null}
                <Badge>{h.kind}</Badge><Badge tone={h.visibility === "public" ? "accent" : "ink"}>{h.visibility}</Badge><span className="text-xs text-muted">v{h.version} · score {h.score.toFixed(4)} · {Object.entries(h.ranks).map(([k, v]) => `${k} #${v}`).join(", ")}</span></div>
              <p className="mt-1 line-clamp-3 text-xs text-muted">{h.text}</p>
            </li>
          ))}
        </ol>
      )) : null}
    </div>
  );
}

function DocPanel({ id, onClose }: { id: string; onClose: () => void }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["doc", id], queryFn: () => api.get<DocDetail>(`/knowledge/${id}`) });
  const status = useMutation<unknown, ApiError, string>({
    mutationFn: (s) => api.post(`/knowledge/${id}/status`, { status: s }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["doc", id] }); qc.invalidateQueries({ queryKey: ["knowledge"] }); },
  });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} />;
  const { document: d, versions } = q.data!;
  const current = versions.find((v) => v.version === d.current_version);
  return (
    <Card title={d.title} actions={<Button variant="ghost" onClick={onClose}>Close</Button>}>
      <div className="flex flex-wrap gap-1 text-xs"><Badge>{d.kind}</Badge><Badge tone={d.visibility === "public" ? "accent" : "ink"}>{d.visibility}</Badge><StatusBadge status={d.status} />{d.component ? <Badge>{d.component}</Badge> : null}{d.customer_account_id ? <Badge tone="warn">account-scoped</Badge> : null}</div>
      <p className="mt-2 text-xs text-muted">valid {fmtDate(d.valid_from)} → {d.valid_to ? fmtDate(d.valid_to) : "open"} · hash <Mono>{shortHash(d.content_hash)}</Mono></p>
      <div className="mt-2 flex flex-wrap gap-2">
        {d.status !== "current" ? <Button onClick={() => status.mutate("current")}>Mark current</Button> : <Button onClick={() => status.mutate("superseded")}>Mark superseded</Button>}
        {d.status !== "retired" ? <Button variant="danger" onClick={() => status.mutate("retired")}>Retire</Button> : null}
        {current ? <a className="inline-flex items-center rounded-md border border-line-strong px-3 py-1.5 text-sm" href={`/api/knowledge/${d.id}/versions/${current.version}/raw`}>Download v{current.version}</a> : null}
      </div>
      {status.error ? <Notice tone="danger">{status.error.detail}</Notice> : null}
      <h3 className="mt-3 text-sm font-semibold">Versions</h3>
      <ul className="text-xs">{versions.map((v) => <li key={v.id}>v{v.version} · <Mono>{shortHash(v.content_hash)}</Mono> · {fmtDate(v.created_at)} {v.valid_to ? `· ended ${fmtDate(v.valid_to)}` : ""} {v.source_filename ? `· ${v.source_filename}` : ""}</li>)}</ul>
      {current?.content ? <pre className="mt-3 max-h-80 overflow-auto rounded bg-paper p-3 text-xs whitespace-pre-wrap">{current.content}</pre> : null}
    </Card>
  );
}

export function KnowledgePage() {
  const [filters, setFilters] = useState({ kind: "", status: "", q: "" });
  const [open, setOpen] = useState<string | null>(null);
  const [tab, setTab] = useState<"library" | "ingest" | "inspect">("library");
  const docs = useQuery({ queryKey: ["knowledge", filters], queryFn: () => api.get<Doc[]>(`/knowledge${qs(filters)}`) });
  const accounts = useQuery({ queryKey: ["accounts"], queryFn: () => api.get<Account[]>("/accounts") });
  return (
    <div>
      <PageHeader title="Knowledge" subtitle="Versioned, scoped sources. Generated drafts are never indexed as knowledge automatically." />
      <div role="tablist" className="mb-4 flex gap-1 border-b border-line">
        {(["library", "ingest", "inspect"] as const).map((k) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)} className={`-mb-px border-b-2 px-3 py-1.5 text-sm ${tab === k ? "border-accent-600 font-medium" : "border-transparent text-muted"}`}>
            {k === "library" ? "Library" : k === "ingest" ? "Ingest" : "Retrieval inspector"}
          </button>
        ))}
      </div>
      {tab === "ingest" ? <Card><Upload accounts={accounts.data} /></Card> : tab === "inspect" ? <Card><Inspector accounts={accounts.data} /></Card> : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_420px]">
          <div>
            <div className="mb-3 grid gap-2 sm:grid-cols-3">
              <Input aria-label="Search titles" placeholder="Search titles" value={filters.q} onChange={(e) => setFilters({ ...filters, q: e.target.value })} />
              <Select aria-label="Kind" value={filters.kind} onChange={(e) => setFilters({ ...filters, kind: e.target.value })}><option value="">Any kind</option>{["policy", "article", "runbook", "release_note", "historical_case"].map((k) => <option key={k}>{k}</option>)}</Select>
              <Select aria-label="Status" value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value })}><option value="">Any status</option><option>current</option><option>superseded</option><option>retired</option></Select>
            </div>
            {docs.isLoading ? <Loading /> : docs.error ? <ErrorState error={docs.error} retry={docs.refetch} /> : docs.data!.length === 0 ? <Empty title="No documents" /> : (
              <ul className="divide-y divide-line rounded-lg border border-line bg-card">
                {docs.data!.map((d) => (
                  <li key={d.id}>
                    <button onClick={() => setOpen(d.id)} className={`flex w-full flex-wrap items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-paper ${open === d.id ? "bg-accent-50" : ""}`}>
                      <span className="min-w-0"><span className="font-medium">{d.title}</span> <span className="text-xs text-muted">v{d.current_version} · {d.slug}</span></span>
                      <span className="flex flex-wrap gap-1"><Badge>{d.kind}</Badge><Badge tone={d.visibility === "public" ? "accent" : "ink"}>{d.visibility}</Badge>{d.status !== "current" ? <StatusBadge status={d.status} /> : null}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          {open ? <DocPanel id={open} onClose={() => setOpen(null)} /> : <Empty title="Select a document">Inspect versions, hashes, validity, and scope.</Empty>}
        </div>
      )}
    </div>
  );
}
