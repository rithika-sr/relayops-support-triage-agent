"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, Button, Card, ErrorState, Field, Input, Loading, Mono, Notice, PageHeader, StatusBadge, Textarea } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { fmtDate, label, shortHash } from "@/lib/format";
import { useMe } from "@/lib/session";

interface Config { focus: string; allowed_tools: string[]; allowed_routes: string[]; max_turns: number; max_tool_calls: number; required_facts: string[]; retrieval_mode: string }
interface PB { id: string; key: string; name: string; description: string; current_revision: number; config: Config; config_hash: string; runs_by_status: Record<string, number> }
interface PBDetail { playbook: PB; config: Config; graph: { nodes: { id: string; label: string; kind: string }[]; tools: string[]; routes: string[] }; revisions: { revision: number; config_hash: string; created_by: string; created_at: string }[]; runs: { id: string; status: string; route: string | null; playbook_revision: number; created_at: string; mode: string }[]; options: { tools: string[]; routes: string[] } }

function Editor({ d, canEdit }: { d: PBDetail; canEdit: boolean }) {
  const qc = useQueryClient();
  const [cfg, setCfg] = useState<Config>(d.config);
  const save = useMutation<PBDetail, ApiError>({
    mutationFn: () => api.post(`/playbooks/${d.playbook.key}/revisions`, { config: cfg }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["playbook", d.playbook.key] }); qc.invalidateQueries({ queryKey: ["playbooks"] }); },
  });
  const toggle = (k: "allowed_tools" | "allowed_routes", v: string) => setCfg({ ...cfg, [k]: cfg[k].includes(v) ? cfg[k].filter((x) => x !== v) : [...cfg[k], v] });
  return (
    <form className="flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
      <Field id="focus" label="Investigator focus"><Textarea id="focus" value={cfg.focus} onChange={(e) => setCfg({ ...cfg, focus: e.target.value })} readOnly={!canEdit} /></Field>
      <fieldset className="text-sm"><legend className="font-medium">Read tools</legend>
        <div className="mt-1 flex flex-wrap gap-3">{d.options.tools.map((t) => <label key={t} className="flex items-center gap-1"><input type="checkbox" checked={cfg.allowed_tools.includes(t)} onChange={() => toggle("allowed_tools", t)} disabled={!canEdit} />{t}</label>)}</div>
      </fieldset>
      <fieldset className="text-sm"><legend className="font-medium">Routes</legend>
        <div className="mt-1 flex flex-wrap gap-3">{d.options.routes.map((r) => <label key={r} className="flex items-center gap-1"><input type="checkbox" checked={cfg.allowed_routes.includes(r)} onChange={() => toggle("allowed_routes", r)} disabled={!canEdit || r === "clarification" || r === "specialist_review"} />{label(r)}</label>)}</div>
        <p className="text-xs text-muted">Clarification and specialist review always stay available as safe exits.</p>
      </fieldset>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Field id="turns" label="Max turns (≤4)"><Input id="turns" type="number" min={1} max={4} value={cfg.max_turns} onChange={(e) => setCfg({ ...cfg, max_turns: Number(e.target.value) })} readOnly={!canEdit} /></Field>
        <Field id="calls" label="Max tool calls (≤6)"><Input id="calls" type="number" min={1} max={6} value={cfg.max_tool_calls} onChange={(e) => setCfg({ ...cfg, max_tool_calls: Number(e.target.value) })} readOnly={!canEdit} /></Field>
        <Field id="facts" label="Required facts"><Input id="facts" value={cfg.required_facts.join(", ")} onChange={(e) => setCfg({ ...cfg, required_facts: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} readOnly={!canEdit} /></Field>
      </div>
      {save.error ? <Notice tone="danger">{save.error.detail}</Notice> : null}
      {canEdit ? <div><Button variant="primary" type="submit" busy={save.isPending}>Save as revision {d.playbook.current_revision + 1}</Button></div> : <p className="text-xs text-muted">Only an organization admin can save playbook revisions.</p>}
    </form>
  );
}

function Detail({ k }: { k: string }) {
  const me = useMe();
  const q = useQuery({ queryKey: ["playbook", k], queryFn: () => api.get<PBDetail>(`/playbooks/${k}`) });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} />;
  const d = q.data!;
  return (
    <div className="flex flex-col gap-4">
      <Card title={`Graph preview · ${d.playbook.name} r${d.playbook.current_revision}`}>
        <ol className="flex flex-wrap items-center gap-1 text-xs">{d.graph.nodes.map((n, i) => (
          <li key={n.id} className="flex items-center gap-1"><span className={`rounded border px-2 py-1 ${n.kind === "human" ? "border-amber-700 bg-amber-50" : n.kind === "code" ? "border-ink-700 bg-white" : "border-teal-600 bg-teal-50"}`}>{n.label}{n.id === "investigate" ? ` ↺ ≤${d.config.max_turns}` : ""}</span>{i < d.graph.nodes.length - 1 ? <span aria-hidden>→</span> : null}</li>
        ))}</ol>
        <p className="mt-2 text-xs text-muted">Tools: {d.graph.tools.join(", ")} · routes: {d.graph.routes.map(label).join(", ")}</p>
      </Card>
      <Card title="Configuration"><Editor key={d.playbook.current_revision} d={d} canEdit={me.data?.role === "admin"} /></Card>
      <div className="grid gap-4 sm:grid-cols-2">
        <Card title="Revisions"><ul className="text-sm">{d.revisions.map((r) => <li key={r.revision}>r{r.revision} · <Mono>{shortHash(r.config_hash)}</Mono> · {fmtDate(r.created_at)}</li>)}</ul></Card>
        <Card title="Recent runs">{d.runs.length ? <ul className="text-sm">{d.runs.map((r) => <li key={r.id}><Link className="font-mono text-xs text-teal-700 hover:underline" href={`/app/investigations/${r.id}`}>{r.id.slice(0, 14)}…</Link> <StatusBadge status={r.status} /> r{r.playbook_revision} {r.mode !== "live" ? <Badge tone="amber">replay</Badge> : null}</li>)}</ul> : <p className="text-sm text-muted">No runs yet.</p>}</Card>
      </div>
    </div>
  );
}

export function PlaybooksPage() {
  const q = useQuery({ queryKey: ["playbooks"], queryFn: () => api.get<PB[]>("/playbooks") });
  const [sel, setSel] = useState("howto");
  return (
    <div>
      <PageHeader title="Playbooks" subtitle="Typed templates that all execute on the same durable investigation graph." />
      {q.isLoading ? <Loading /> : q.error ? <ErrorState error={q.error} /> : (
        <div className="grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
          <ul className="flex flex-col gap-2">{q.data!.map((p) => (
            <li key={p.key}><button onClick={() => setSel(p.key)} aria-pressed={sel === p.key} className={`w-full rounded-lg border px-3 py-2 text-left ${sel === p.key ? "border-teal-600 bg-teal-50" : "border-line bg-card hover:bg-paper"}`}>
              <p className="font-medium">{p.name} <span className="text-xs text-muted">r{p.current_revision}</span></p>
              <p className="text-xs text-muted">{p.description}</p>
              <p className="mt-1 text-xs">{Object.entries(p.runs_by_status).map(([s, n]) => `${n} ${label(s)}`).join(" · ") || "no runs"}</p>
            </button></li>
          ))}</ul>
          <Detail k={sel} />
        </div>
      )}
    </div>
  );
}
