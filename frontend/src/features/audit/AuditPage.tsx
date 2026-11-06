"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Button, Empty, ErrorState, Loading, PageHeader, Select, StatusBadge } from "@/components/ui";
import { api, qs } from "@/lib/api";
import { fmtDate } from "@/lib/format";

interface AuditRow { id: string; action: string; actor_kind: string; actor_user_id: string | null; target_type: string; target_id: string; outcome: string; detail: Record<string, unknown>; created_at: string }

export function AuditPage() {
  const [action, setAction] = useState("");
  const [outcome, setOutcome] = useState("");
  const [page, setPage] = useState(1);
  const q = useQuery({ queryKey: ["audit", action, outcome, page], queryFn: () => api.get<{ items: AuditRow[] }>(`/audit${qs({ action, outcome, page })}`) });
  return (
    <div>
      <PageHeader title="Audit" subtitle="Reviews, edits, policy and playbook changes, actions, and failed or unknown effects in your organization." />
      <div className="mb-3 grid max-w-lg gap-2 sm:grid-cols-2">
        <Select aria-label="Action" value={action} onChange={(e) => { setAction(e.target.value); setPage(1); }}>
          <option value="">All actions</option>
          {["proposal", "action", "investigation", "ticket", "knowledge", "incident", "playbook", "artifact", "auth", "invitation", "api_token", "evaluation"].map((a) => <option key={a} value={a}>{a}.*</option>)}
        </Select>
        <Select aria-label="Outcome" value={outcome} onChange={(e) => { setOutcome(e.target.value); setPage(1); }}><option value="">Any outcome</option><option value="ok">ok</option><option value="failed">failed</option><option value="unknown">unknown</option><option value="denied">denied</option></Select>
      </div>
      {q.isLoading ? <Loading /> : q.error ? <ErrorState error={q.error} /> : q.data!.items.length === 0 ? <Empty title="No audit events match" /> : (
        <div className="overflow-x-auto rounded-lg border border-line bg-card">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="border-b border-line bg-paper text-left text-xs text-muted uppercase"><tr><th className="px-3 py-2">When</th><th className="px-3 py-2">Action</th><th className="px-3 py-2">Actor</th><th className="px-3 py-2">Target</th><th className="px-3 py-2">Outcome</th><th className="px-3 py-2">Detail</th></tr></thead>
            <tbody className="divide-y divide-line">{q.data!.items.map((e) => (
              <tr key={e.id}><td className="px-3 py-2 whitespace-nowrap text-muted">{fmtDate(e.created_at)}</td><td className="px-3 py-2 font-mono text-xs">{e.action}</td><td className="px-3 py-2 text-xs">{e.actor_kind}{e.actor_user_id ? ` ${e.actor_user_id.slice(0, 12)}` : ""}</td><td className="px-3 py-2 text-xs">{e.target_type} {e.target_id.slice(0, 16)}</td><td className="px-3 py-2"><StatusBadge status={e.outcome === "ok" ? "passed" : e.outcome} /></td><td className="max-w-md truncate px-3 py-2 font-mono text-xs text-muted" title={JSON.stringify(e.detail)}>{JSON.stringify(e.detail)}</td></tr>
            ))}</tbody>
          </table>
        </div>
      )}
      <div className="mt-3 flex gap-2"><Button disabled={page <= 1} onClick={() => setPage(page - 1)}>Newer</Button><Button disabled={(q.data?.items.length ?? 0) < 100} onClick={() => setPage(page + 1)}>Older</Button></div>
    </div>
  );
}
