"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, Button, Card, Empty, ErrorState, Loading, Mono, Notice, PageHeader, Select, StatusBadge, Textarea } from "@/components/ui";
import { api, ApiError, qs } from "@/lib/api";
import { fmtDate, label, shortHash } from "@/lib/format";
import type { ArtifactSummary, Check } from "@/lib/types";

interface Version { version: number; content: string; content_hash: string; sources: { id?: string; title?: string; source_type?: string }[]; verification: { status?: string; checks?: Check[]; note?: string }; verification_status: string; verified_content_hash: string | null; created_by: string; note: string | null; created_at: string }

function ContentEditor({ initial, editable, nextVersion, saving, revalidating, onSave, onRevalidate }: {
  initial: string; editable: boolean; nextVersion: number; saving: boolean; revalidating: boolean;
  onSave: (content: string) => void; onRevalidate: () => void;
}) {
  const [content, setContent] = useState(initial);
  return (
    <>
      <Textarea aria-label="Artifact content" className="mt-3 min-h-72 font-mono text-xs" value={content} onChange={(e) => setContent(e.target.value)} readOnly={!editable} />
      {editable ? (
        <div className="mt-2 flex flex-wrap gap-2">
          <Button onClick={() => onSave(content)} busy={saving} disabled={content === initial}>Save as v{nextVersion}</Button>
          <Button variant="primary" onClick={onRevalidate} busy={revalidating}>Re-run verification</Button>
          <span className="text-xs text-muted">Editing marks verification stale until it is re-run.</span>
        </div>
      ) : null}
    </>
  );
}

function Detail({ id }: { id: string }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["artifact", id], queryFn: () => api.get<{ artifact: ArtifactSummary; versions: Version[] }>(`/artifacts/${id}`) });
  const [view, setView] = useState<number | null>(null);
  const refresh = () => { qc.invalidateQueries({ queryKey: ["artifact", id] }); qc.invalidateQueries({ queryKey: ["artifacts"] }); };
  const edit = useMutation<unknown, ApiError, string>({ mutationFn: (content) => api.post(`/artifacts/${id}/versions`, { content }), onSuccess: refresh });
  const reval = useMutation<unknown, ApiError>({ mutationFn: () => api.post(`/artifacts/${id}/revalidate`), onSuccess: refresh });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} />;
  const { artifact: a, versions } = q.data!;
  const v = versions.find((x) => x.version === view) ?? versions[0];
  const isLatest = v.version === a.current_version;
  const editable = a.kind !== "customer_reply" && a.review_status !== "approved";
  return (
    <Card title={a.title}>
      <div className="flex flex-wrap items-center gap-1"><Badge>{label(a.kind)}</Badge><StatusBadge status={a.review_status} /><StatusBadge status={v.verification_status} />
        <span className="text-xs text-muted">hash <Mono title={v.content_hash}>{shortHash(v.content_hash)}</Mono> {v.verified_content_hash && v.verified_content_hash !== v.content_hash ? "(verified hash differs)" : ""}</span></div>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Select aria-label="Version" value={v.version} onChange={(e) => setView(Number(e.target.value))} className="w-40">{versions.map((x) => <option key={x.version} value={x.version}>v{x.version} · {x.verification_status}</option>)}</Select>
        <a className="inline-flex items-center rounded-md border border-line-strong px-3 py-1.5 text-sm" href={`/api/artifacts/${a.id}/export?format=md`}>Export Markdown</a>
        <a className="inline-flex items-center rounded-md border border-line-strong px-3 py-1.5 text-sm" href={`/api/artifacts/${a.id}/export?format=json`}>Export JSON</a>
        {a.run_id ? <Link className="text-sm text-teal-700 hover:underline" href={`/app/investigations/${a.run_id}`}>Open investigation</Link> : null}
      </div>
      {a.kind === "customer_reply" ? <Notice tone="teal">Reply drafts are edited in the review panel so each edit becomes a new proposal version and is re-verified.</Notice> : null}
      {a.review_status === "approved" ? <Notice tone="ok">Approved artifacts are immutable.</Notice> : null}
      <ContentEditor key={`${v.version}`} initial={v.content} editable={editable && isLatest} nextVersion={a.current_version + 1}
        saving={edit.isPending} revalidating={reval.isPending} onSave={(c) => edit.mutate(c)} onRevalidate={() => reval.mutate()} />
      {edit.error ?? reval.error ? <Notice tone="danger">{(edit.error ?? reval.error)!.detail}</Notice> : null}
      {v.verification.checks?.length ? (
        <ul className="mt-3 text-sm">{v.verification.checks.map((c) => <li key={c.name}><StatusBadge status={c.status} /> {label(c.name)} <span className="text-xs text-muted">{c.detail}</span></li>)}</ul>
      ) : <p className="mt-3 text-xs text-muted">{v.verification_status === "stale" ? "Verification is stale for this version." : "No verification recorded for this version."}</p>}
      <p className="mt-2 text-xs text-muted">Created by {v.created_by} · {fmtDate(v.created_at)} {v.note ? `· ${v.note}` : ""} · {v.sources.length} sources</p>
    </Card>
  );
}

export function ArtifactsPage() {
  const [kind, setKind] = useState("");
  const [sel, setSel] = useState<string | null>(null);
  const q = useQuery({ queryKey: ["artifacts", kind], queryFn: () => api.get<ArtifactSummary[]>(`/artifacts${qs({ kind })}`) });
  return (
    <div>
      <PageHeader title="Artifacts" subtitle="Immutable versions of reply drafts, engineering briefs, and incident summaries, each bound to a content hash." />
      <div className="mb-3 max-w-xs"><Select aria-label="Kind" value={kind} onChange={(e) => setKind(e.target.value)}><option value="">All kinds</option><option value="customer_reply">Customer replies</option><option value="engineering_brief">Engineering briefs</option><option value="incident_summary">Incident summaries</option></Select></div>
      {q.isLoading ? <Loading /> : q.error ? <ErrorState error={q.error} /> : q.data!.length === 0 ? <Empty title="No artifacts yet">Investigations and incident summaries create them.</Empty> : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
          <ul className="divide-y divide-line self-start rounded-lg border border-line bg-card">{q.data!.map((a) => (
            <li key={a.id}><button onClick={() => setSel(a.id)} aria-pressed={sel === a.id} className={`w-full px-3 py-2 text-left text-sm hover:bg-paper ${sel === a.id ? "bg-teal-50" : ""}`}>
              <p className="font-medium">{a.title}</p>
              <p className="mt-0.5 flex flex-wrap gap-1"><Badge>{label(a.kind)}</Badge><Badge>v{a.current_version}</Badge><StatusBadge status={a.verification_status} /><StatusBadge status={a.review_status} /></p>
            </button></li>
          ))}</ul>
          {sel ? <Detail id={sel} /> : <Empty title="Select an artifact" />}
        </div>
      )}
    </div>
  );
}
