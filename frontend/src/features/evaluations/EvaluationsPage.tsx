"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Badge, Button, Card, Empty, ErrorState, Loading, Notice, PageHeader, Select, StatusBadge } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { label } from "@/lib/format";

interface Metric { numerator: number; denominator: number; value: number | null }
interface SystemSummary { system: string; cases_run: number; cases_failed: number; route_accuracy?: Metric; evidence_recall_at_k?: Metric; provenance_validity?: Metric; latency_ms?: { p50: number | null; p95: number | null }; [k: string]: unknown }
interface Report { id: string; report_key: string; profile: string; metadata: Record<string, unknown>; summary: { systems?: SystemSummary[]; unrun_cases?: number; total_cases?: number; [k: string]: unknown }; case_count: number; source_path: string; notes: string | null }
interface CaseRow { case_id: string; system: string; split: string; status: string; expected_route?: string; actual_route?: string | null; route_correct?: boolean | null; evidence_ids?: string[]; tool_path?: string[]; latency_ms?: number | null; failures?: string[]; input?: string; policy_version?: string }

const pct = (m?: Metric) => (m && m.value !== null ? `${(m.value * 100).toFixed(0)}% (${m.numerator}/${m.denominator})` : "—");

function Detail({ id }: { id: string }) {
  const q = useQuery({ queryKey: ["eval", id], queryFn: () => api.get<Report & { cases: CaseRow[] }>(`/evaluations/${id}`) });
  const [system, setSystem] = useState("");
  const [onlyFail, setOnlyFail] = useState(true);
  const [open, setOpen] = useState<string | null>(null);
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} />;
  const r = q.data!;
  const systems = r.summary.systems ?? [];
  const chart = systems.map((s) => ({ system: s.system, route: s.route_accuracy?.value ?? null, recall: s.evidence_recall_at_k?.value ?? null }));
  const cases = r.cases.filter((c) => (!system || c.system === system) && (!onlyFail || c.status !== "passed"));
  return (
    <div className="flex flex-col gap-4">
      <Card title="Run metadata">
        <dl className="grid gap-x-4 gap-y-1 text-xs sm:grid-cols-2">{Object.entries(r.metadata).map(([k, v]) => <div key={k} className="contents"><dt className="text-muted">{label(k)}</dt><dd className="truncate font-mono" title={typeof v === "object" ? JSON.stringify(v) : String(v)}>{typeof v === "object" ? JSON.stringify(v) : String(v)}</dd></div>)}</dl>
        {r.notes ? <Notice tone="amber">{r.notes}</Notice> : null}
        <p className="mt-2 text-xs text-muted">Source file {r.source_path}. Unrun cases: {String(r.summary.unrun_cases ?? 0)} of {String(r.summary.total_cases ?? r.case_count)}.</p>
      </Card>
      <Card title="Baseline comparison (measured)">
        {systems.length === 0 ? <Empty title="No system summaries in this report" /> : (
          <>
            <div className="overflow-x-auto"><table className="w-full min-w-[640px] text-sm"><thead className="text-left text-xs text-muted uppercase"><tr><th className="py-1">System</th><th>Cases run</th><th>Failed / errors</th><th>Route accuracy</th><th>Evidence recall@k</th><th>Provenance validity</th><th>Latency p50 / p95</th></tr></thead>
              <tbody>{systems.map((s) => <tr key={s.system} className="border-t border-line"><td className="py-1 font-medium">{s.system}</td><td>{s.cases_run}</td><td>{s.cases_failed}</td><td>{pct(s.route_accuracy)}</td><td>{pct(s.evidence_recall_at_k)}</td><td>{pct(s.provenance_validity)}</td><td>{s.latency_ms?.p50 ?? "—"} / {s.latency_ms?.p95 ?? "—"} ms</td></tr>)}</tbody></table></div>
            <div className="mt-3 h-56"><ResponsiveContainer width="100%" height="100%"><BarChart data={chart}><CartesianGrid vertical={false} stroke="#e5ddd0" /><XAxis dataKey="system" tick={{ fontSize: 12 }} /><YAxis domain={[0, 1]} tick={{ fontSize: 12 }} /><Tooltip /><Legend /><Bar dataKey="route" name="route accuracy" fill="#0f7f76" /><Bar dataKey="recall" name="evidence recall@k" fill="#9a5a07" /></BarChart></ResponsiveContainer></div>
          </>
        )}
      </Card>
      <Card title={`Per-case results (${cases.length})`} actions={<span className="flex items-center gap-2"><Select aria-label="System" value={system} onChange={(e) => setSystem(e.target.value)} className="w-40"><option value="">All systems</option>{systems.map((s) => <option key={s.system}>{s.system}</option>)}</Select><label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={onlyFail} onChange={(e) => setOnlyFail(e.target.checked)} />failures only</label></span>}>
        {cases.length === 0 ? <Empty title="No cases match" /> : (
          <ul className="divide-y divide-line text-sm">{cases.map((c) => {
            const key = `${c.system}:${c.case_id}`;
            return (
              <li key={key} className="py-1.5">
                <button className="flex w-full flex-wrap items-center gap-2 text-left" onClick={() => setOpen(open === key ? null : key)} aria-expanded={open === key}>
                  <span className="font-mono text-xs">{c.case_id}</span><Badge>{c.system}</Badge><Badge>{c.split}</Badge><StatusBadge status={c.status} />
                  <span className="text-xs text-muted">expected {label(c.expected_route)} · actual {label(c.actual_route ?? "none")}</span>
                </button>
                {open === key ? (
                  <div className="mt-1 rounded bg-paper p-2 text-xs">
                    {c.input ? <p><span className="font-medium">Input:</span> {c.input}</p> : null}
                    <p><span className="font-medium">Failures:</span> {c.failures?.join("; ") || "none"}</p>
                    <p><span className="font-medium">Evidence:</span> {c.evidence_ids?.join(", ") || "none"}</p>
                    <p><span className="font-medium">Tool path:</span> {c.tool_path?.join(" → ") || "none"}</p>
                    <p><span className="font-medium">Latency:</span> {c.latency_ms ?? "—"} ms · policy {c.policy_version ?? "—"}</p>
                  </div>
                ) : null}
              </li>
            );
          })}</ul>
        )}
      </Card>
    </div>
  );
}

export function EvaluationsPage() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["evals"], queryFn: () => api.get<Report[]>("/evaluations") });
  const imp = useMutation<{ loaded: string[]; skipped: { file: string; reason: string }[] }, ApiError>({ mutationFn: () => api.post("/evaluations/import"), onSuccess: () => qc.invalidateQueries({ queryKey: ["evals"] }) });
  const [sel, setSel] = useState<string | null>(null);
  return (
    <div>
      <PageHeader title="Evaluations" subtitle="Reports produced by evals/runners with actual denominators. Unrun cases stay marked unrun." actions={<Button variant="primary" onClick={() => imp.mutate()} busy={imp.isPending}>Import reports from evals/results</Button>} />
      {imp.data ? <Notice tone="ok">Loaded {imp.data.loaded.length} report(s).{imp.data.skipped.length ? ` Skipped: ${imp.data.skipped.map((s) => `${s.file} (${s.reason})`).join(", ")}` : ""}</Notice> : null}
      {imp.error ? <Notice tone="danger">{imp.error.detail}</Notice> : null}
      <Notice tone="amber">Human claim-support review: pending. No human annotations have been recorded; automated checks are not relabeled as human review.</Notice>
      {q.isLoading ? <Loading /> : q.error ? <ErrorState error={q.error} /> : q.data!.length === 0 ? <div className="mt-4"><Empty title="No reports imported">Run <code>make eval-offline</code> or <code>make eval-live-smoke</code>, then import.</Empty></div> : (
        <div className="mt-4 grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)]">
          <ul className="flex flex-col gap-2 self-start">{q.data!.map((r) => (
            <li key={r.id}><button onClick={() => setSel(r.id)} aria-pressed={sel === r.id} className={`w-full rounded-lg border px-3 py-2 text-left text-sm ${sel === r.id ? "border-teal-600 bg-teal-50" : "border-line bg-card hover:bg-paper"}`}>
              <p className="font-medium">{r.report_key}</p><p className="text-xs text-muted">{r.profile} · {r.case_count} case results</p>
            </button></li>
          ))}</ul>
          {sel ? <Detail id={sel} /> : <Empty title="Select a report" />}
        </div>
      )}
    </div>
  );
}
