"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Badge, Empty, ErrorState, Loading, PageHeader, Select, StatusBadge } from "@/components/ui";
import { api, qs } from "@/lib/api";
import { label, relative } from "@/lib/format";
import type { RunSummary } from "@/lib/types";

export function InvestigationsList() {
  const params = useSearchParams();
  const router = useRouter();
  const path = usePathname();
  const f = { status: params.get("status") ?? "", mode: params.get("mode") ?? "", playbook: params.get("playbook") ?? "" };
  const set = (k: string, v: string) => {
    const n = new URLSearchParams(params.toString());
    if (v) n.set(k, v); else n.delete(k);
    router.replace(`${path}?${n}`);
  };
  const q = useQuery({ queryKey: ["runs", f], queryFn: () => api.get<{ items: RunSummary[] }>(`/investigations${qs(f)}`), refetchInterval: 10_000 });
  return (
    <div>
      <PageHeader title="Investigations" subtitle="Persisted runs with their route, budgets used, and model identity." />
      <div className="mb-3 grid max-w-2xl gap-2 sm:grid-cols-3">
        <Select aria-label="Status" value={f.status} onChange={(e) => set("status", e.target.value)}>
          <option value="">Any status</option>
          {["queued", "running", "awaiting_review", "executing", "completed", "rejected", "failed", "cancelled"].map((s) => <option key={s} value={s}>{label(s)}</option>)}
        </Select>
        <Select aria-label="Mode" value={f.mode} onChange={(e) => set("mode", e.target.value)}>
          <option value="">Live and replays</option><option value="live">Live runs</option><option value="recorded_replay">Recorded replays</option>
        </Select>
        <Select aria-label="Playbook" value={f.playbook} onChange={(e) => set("playbook", e.target.value)}>
          <option value="">Any playbook</option>
          {["howto", "bug", "feature", "incident"].map((s) => <option key={s} value={s}>{s}</option>)}
        </Select>
      </div>
      {q.isLoading ? <Loading /> : q.error ? <ErrorState error={q.error} retry={q.refetch} /> : q.data!.items.length === 0 ? (
        <Empty title="No investigations match">Start one from a ticket in the inbox.</Empty>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-line bg-card">
          <table className="w-full min-w-[760px] text-sm">
            <thead className="border-b border-line bg-paper text-left text-xs text-muted uppercase">
              <tr><th className="px-3 py-2">Run</th><th className="px-3 py-2">Ticket</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Route</th><th className="px-3 py-2">Usage</th><th className="px-3 py-2">Model</th><th className="px-3 py-2">Created</th></tr>
            </thead>
            <tbody className="divide-y divide-line">
              {q.data!.items.map((r) => (
                <tr key={r.id} className="hover:bg-paper">
                  <td className="px-3 py-2"><Link className="font-mono text-xs text-accent-700 hover:underline" href={`/app/investigations/${r.id}`}>{r.id}</Link>
                    <div className="mt-0.5 flex gap-1"><Badge>{r.playbook}</Badge>{r.mode === "recorded_replay" ? <Badge tone="warn">replay</Badge> : null}{r.compare_of_run_id ? <Badge tone="accent">compare</Badge> : null}</div></td>
                  <td className="px-3 py-2">#{r.ticket_number} {r.ticket_subject}</td>
                  <td className="px-3 py-2"><StatusBadge status={r.status} /></td>
                  <td className="px-3 py-2">{label(r.route)}</td>
                  <td className="px-3 py-2 text-xs text-muted">{r.usage.turns ?? 0} turns · {r.usage.tool_calls ?? 0} tools · {r.usage.model_calls ?? 0} model</td>
                  <td className="px-3 py-2 text-xs">{r.model_provider === "fixture" ? <Badge tone="danger">fixture</Badge> : r.model_name}</td>
                  <td className="px-3 py-2 text-muted">{relative(r.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
