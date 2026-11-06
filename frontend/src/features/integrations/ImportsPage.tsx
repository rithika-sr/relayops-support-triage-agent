"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, Button, Card, ErrorState, Field, Input, Notice, PageHeader, Skeleton, StatusBadge, useToast } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { fmtDate } from "@/lib/format";

interface PreviewRow { row: number; external_id: string | null; status: "ok" | "duplicate" | "error"; errors: string[]; account?: string; subject?: string }
interface Preview { rows: PreviewRow[]; counts: Record<string, number>; content_sha256: string }
interface Batch { id: string; filename: string; created_count: number; duplicate_count: number; error_count: number; total_rows: number; created_at: string }

export function ImportsPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const batches = useQuery({ queryKey: ["imports"], queryFn: () => api.get<Batch[]>("/imports") });
  const form = (extra?: Record<string, string>) => { const fd = new FormData(); if (file) fd.append("file", file); Object.entries(extra ?? {}).forEach(([k, v]) => fd.append(k, v)); return fd; };
  const check = useMutation<Preview, ApiError>({ mutationFn: () => api.post("/imports/preview", form()), onSuccess: setPreview });
  const commit = useMutation<Batch, ApiError>({
    mutationFn: () => api.post("/imports", form({ expected_sha256: preview!.content_sha256 })),
    onSuccess: (b) => { toast(`Imported ${b.created_count} tickets`); setPreview(null); setFile(null); qc.invalidateQueries({ queryKey: ["imports"] }); qc.invalidateQueries({ queryKey: ["tickets"] }); },
  });
  return (
    <div>
      <PageHeader title="Import tickets" subtitle="Bring existing tickets in from a CSV or JSON export. Preview first; nothing is written until you confirm." />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
        <Card title="1. Choose a file">
          <div className="flex flex-col gap-3">
            <Field id="file" label="CSV or JSON (UTF-8, up to 1 MB and 1,000 rows)" hint="Columns: external_id, account (name or ID), subject, body, and optionally severity, component, product_version, error_code, occurred_at.">
              <Input id="file" type="file" accept=".csv,.json,text/csv,application/json" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setPreview(null); }} />
            </Field>
            <div><Button variant="primary" disabled={!file} busy={check.isPending} onClick={() => check.mutate()}>Preview import</Button></div>
            {check.error ? <Notice tone="danger">{check.error.detail}</Notice> : null}
            {preview ? (
              <div className="flex flex-col gap-3">
                <h3 className="font-semibold">2. Review the preview</h3>
                <p className="flex flex-wrap gap-2 text-sm"><Badge tone="ok">{preview.counts.ok} ready</Badge><Badge>{preview.counts.duplicate} duplicates</Badge><Badge tone="danger">{preview.counts.error} errors</Badge></p>
                <ul className="max-h-80 divide-y divide-line overflow-y-auto rounded-lg border border-line text-sm">
                  {preview.rows.map((r) => (
                    <li key={r.row} className="flex flex-wrap items-center gap-2 px-3 py-2">
                      <span className="w-14 text-muted">row {r.row}</span><StatusBadge status={r.status === "ok" ? "passed" : r.status === "error" ? "failed" : "duplicate"} />
                      <span className="min-w-0 flex-1 truncate">{r.subject ?? r.external_id}{r.account ? ` · ${r.account}` : ""}</span>
                      {r.errors.length ? <span className="w-full text-[13px] text-danger-700">{r.errors.join("; ")}</span> : null}
                    </li>
                  ))}
                </ul>
                <div><Button variant="primary" disabled={!preview.counts.ok} busy={commit.isPending} onClick={() => commit.mutate()}>Import {preview.counts.ok} tickets</Button></div>
                {commit.error ? <Notice tone="danger">{commit.error.detail}</Notice> : null}
                <p className="text-[13px] text-muted">Imported tickets are labeled with their source file. Importing the same file again creates nothing new.</p>
              </div>
            ) : null}
          </div>
        </Card>
        <Card title="Previous imports">
          {batches.isLoading ? <Skeleton /> : batches.error ? <ErrorState error={batches.error} /> : batches.data!.length === 0 ? <p className="text-sm text-muted">No imports yet.</p> : (
            <ul className="flex flex-col gap-2 text-sm">{batches.data!.map((b) => (
              <li key={b.id}><p className="font-medium">{b.filename}</p><p className="text-[13px] text-muted">{fmtDate(b.created_at)} · {b.created_count} created, {b.duplicate_count} duplicates, {b.error_count} errors of {b.total_rows}</p></li>
            ))}</ul>
          )}
        </Card>
      </div>
    </div>
  );
}
