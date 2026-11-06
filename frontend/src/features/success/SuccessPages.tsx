"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { Badge, Button, Card, Disclosure, Empty, ErrorState, Field, Input, Loading, Notice, PageHeader, Select, Textarea, useToast } from "@/components/ui";
import { OnboardingList, type Onboarding } from "@/features/portal/GettingStarted";
import { api, ApiError } from "@/lib/api";
import { fmtDate, label } from "@/lib/format";
import { useMe } from "@/lib/session";

interface AccountRow { id: string; name: string; plan: string; tickets: number; signins: number; help_searches: number; articles_read: number; escalations: number; friction: string[]; onboarding: number; onboarding_total: number }
interface Accounts { window_days: number; data_classes_included: string[]; accounts: AccountRow[] }
interface Cell { week: number; status: "pending" | "measured"; active?: number; eligible?: number; rate?: number }
interface Retention { cohorts: { cohort_week: string; accounts: number; weeks: Cell[] }[]; note: string; data_classes_included: string[] }
interface Opp { kind: string; title: string; evidence: string; rule: string; target: Record<string, string> }
interface Experiment {
  id: string; key: string; hypothesis: string; metric: string; variants: string[]; min_accounts_per_variant: number; status: string; started_at: string | null; stopped_at: string | null;
  results: { status: string; variants?: Record<string, { accounts: number; escalated: number; rate: number | null }>; difference?: { of: string; estimate: number; ci95: [number, number]; method: string }; note?: string };
}

const Basis = ({ classes }: { classes: string[] }) => <span>Counts {classes.join(", ")} records only.</span>;

function AccountOnboarding({ id }: { id: string }) {
  const q = useQuery({ queryKey: ["cs-onboarding", id], queryFn: () => api.get<Onboarding>(`/success/accounts/${id}/onboarding`) });
  return q.data ? <OnboardingList data={q.data} /> : <Loading />;
}

export function AccountsPage() {
  const q = useQuery({ queryKey: ["cs-accounts"], queryFn: () => api.get<Accounts>("/success/accounts") });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} retry={q.refetch} />;
  const d = q.data!;
  return (
    <div>
      <PageHeader title="Accounts" subtitle={<>Adoption and friction over the last {d.window_days} days. Signals are listed separately, not combined into a score. <Basis classes={d.data_classes_included} /></>} />
      {!d.accounts.length ? <Empty title="No customer accounts yet" /> : (
        <div className="flex flex-col gap-3">
          {d.accounts.map((a) => (
            <Card key={a.id} title={<span className="flex flex-wrap items-center gap-2">{a.name}<Badge>{a.plan}</Badge><span className="text-sm font-normal text-muted">onboarding {a.onboarding} of {a.onboarding_total}</span></span>}>
              <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-5">
                {([["Tickets", a.tickets], ["Sign-ins", a.signins], ["Help searches", a.help_searches], ["Articles read", a.articles_read], ["Contacted from Help", a.escalations]] as const).map(([k, v]) => (
                  <div key={k} className="rounded border border-line px-3 py-2"><dt className="text-muted">{k}</dt><dd className="text-lg font-semibold tabular-nums">{v}</dd></div>
                ))}
              </dl>
              {a.friction.length ? (
                <ul className="mt-3 flex flex-col gap-1 text-sm">{a.friction.map((f) => <li key={f} className="flex gap-2"><Badge tone="warn">friction</Badge>{f}</li>)}</ul>
              ) : <p className="mt-3 text-sm text-muted">No friction signals in this window.</p>}
              <Disclosure summary="Onboarding steps"><AccountOnboarding id={a.id} /></Disclosure>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

export function RetentionPage() {
  const q = useQuery({ queryKey: ["cs-retention"], queryFn: () => api.get<Retention>("/success/retention") });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} retry={q.refetch} />;
  const d = q.data!;
  const weeks = d.cohorts[0]?.weeks.length ?? 0;
  return (
    <div>
      <PageHeader title="Retention" subtitle={<>Weekly cohorts by first customer activity. {d.note} <Basis classes={d.data_classes_included} /></>} />
      {!d.cohorts.length ? <Empty title="No customer activity recorded yet">Cohorts appear once customers sign in, search Help, or open tickets.</Empty> : (
        <div className="overflow-x-auto rounded-lg border border-line bg-card">
          <table className="w-full text-sm">
            <caption className="sr-only">Share of each cohort active in week k after its first activity</caption>
            <thead><tr className="border-b border-line text-left text-muted"><th className="px-3 py-2 font-normal">Cohort (week of)</th><th className="px-3 font-normal">Accounts</th>{Array.from({ length: weeks }, (_, k) => <th key={k} className="px-3 font-normal">Week {k}</th>)}</tr></thead>
            <tbody>
              {d.cohorts.map((c) => (
                <tr key={c.cohort_week} className="border-b border-line last:border-0">
                  <td className="px-3 py-2">{c.cohort_week}</td><td className="px-3 tabular-nums">{c.accounts}</td>
                  {c.weeks.map((w) => (
                    <td key={w.week} className="px-3 tabular-nums">{w.status === "pending" ? <span className="text-muted">pending</span> : <span title={`${w.active} of ${w.eligible}`}>{Math.round((w.rate ?? 0) * 100)}%</span>}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

const OPP_TONE: Record<string, "warn" | "info" | "neutral"> = { improve_article: "warn", knowledge_gap: "info", reach_out: "neutral" };

export function OpportunitiesPage() {
  const q = useQuery({ queryKey: ["cs-opps"], queryFn: () => api.get<{ cards: Opp[]; window_days: number; data_classes_included: string[] }>("/success/opportunities") });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorState error={q.error} retry={q.refetch} />;
  const d = q.data!;
  return (
    <div>
      <PageHeader title="Opportunities" subtitle={<>Each card comes from a written rule over the last {d.window_days} days and shows its evidence. <Basis classes={d.data_classes_included} /></>} />
      {!d.cards.length ? <Empty title="Nothing meets a rule yet">Cards appear when articles get repeated “not helpful” votes, searches keep finding nothing, or an account opens several tickets on one area.</Empty> : (
        <ul className="grid gap-3 md:grid-cols-2">
          {d.cards.map((c, i) => (
            <li key={i}>
              <Card title={<span className="flex items-center gap-2"><Badge tone={OPP_TONE[c.kind] ?? "neutral"}>{label(c.kind)}</Badge>{c.title}</span>}>
                <p className="text-sm">{c.evidence}</p>
                <p className="mt-1 text-xs text-muted">Rule: {c.rule}</p>
                {c.target.document_id ? <Link className="mt-2 inline-block text-sm text-accent-700 hover:underline" href={`/app/knowledge?doc=${c.target.document_id}`}>Open article</Link> : null}
                {c.target.account_id ? <Link className="mt-2 inline-block text-sm text-accent-700 hover:underline" href={`/app/inbox?account_id=${c.target.account_id}&component=${c.target.component ?? ""}`}>See tickets</Link> : null}
              </Card>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function ExperimentsPage() {
  const me = useMe();
  const isAdmin = me.data?.role === "admin";
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["experiments"], queryFn: () => api.get<Experiment[]>("/experiments") });
  const [f, setF] = useState({ key: "", hypothesis: "", min: "50", variants: "lexical,rrf" });
  const create = useMutation<unknown, ApiError>({
    mutationFn: () => api.post("/experiments", { key: f.key, hypothesis: f.hypothesis, variants: f.variants.split(","), min_accounts_per_variant: Number(f.min) }),
    onSuccess: () => { toast("Experiment saved as a draft"); qc.invalidateQueries({ queryKey: ["experiments"] }); },
  });
  const act = useMutation<unknown, ApiError, { id: string; action: string }>({
    mutationFn: ({ id, action }) => api.post(`/experiments/${id}/${action}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["experiments"] }),
  });
  return (
    <div>
      <PageHeader title="Experiments" subtitle="One surface: how customer Help ranks results. Accounts are assigned by a stable hash; results stay hidden until every variant reaches its pre-registered minimum." />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="flex flex-col gap-3">
          {q.isLoading ? <Loading /> : q.error ? <ErrorState error={q.error} /> : !q.data!.length ? <Empty title="No experiments" /> : q.data!.map((e) => (
            <Card key={e.id} title={<span className="flex items-center gap-2">{e.key}<Badge tone={e.status === "running" ? "info" : "neutral"}>{e.status}</Badge></span>}
              actions={isAdmin && e.status !== "stopped" ? <Button size="sm" busy={act.isPending} onClick={() => act.mutate({ id: e.id, action: e.status === "draft" ? "start" : "stop" })}>{e.status === "draft" ? "Start" : "Stop"}</Button> : null}>
              <p className="text-sm">{e.hypothesis}</p>
              <p className="mt-1 text-xs text-muted">Metric: share of searching accounts that contact support from Help · minimum {e.min_accounts_per_variant} accounts per variant{e.started_at ? ` · started ${fmtDate(e.started_at)}` : ""}{e.stopped_at ? ` · stopped ${fmtDate(e.stopped_at)}` : ""}</p>
              {e.results.variants ? (
                <table className="mt-3 w-full text-sm">
                  <thead><tr className="text-left text-muted"><th className="font-normal">Variant</th><th className="font-normal">Accounts</th><th className="font-normal">Contacted support</th></tr></thead>
                  <tbody>{Object.entries(e.results.variants).map(([v, r]) => (
                    <tr key={v} className="border-t border-line"><td className="py-1.5">{v}</td><td className="tabular-nums">{r.accounts}</td><td className="tabular-nums">{e.results.status === "measured" && r.rate !== null ? `${(r.rate * 100).toFixed(1)}%` : "hidden until minimum"}</td></tr>
                  ))}</tbody>
                </table>
              ) : null}
              {e.results.status === "insufficient_sample" ? <Notice>Not enough accounts yet. No comparison is shown.</Notice> : null}
              {e.results.difference ? <p className="mt-2 text-sm">{e.results.difference.of}: {(e.results.difference.estimate * 100).toFixed(1)} points (95% interval {(e.results.difference.ci95[0] * 100).toFixed(1)} to {(e.results.difference.ci95[1] * 100).toFixed(1)}; {e.results.difference.method})</p> : null}
              {e.results.note ? <p className="mt-1 text-xs text-muted">{e.results.note}</p> : null}
            </Card>
          ))}
          {act.error ? <Notice tone="danger">{act.error.detail}</Notice> : null}
        </div>
        {isAdmin ? (
          <Card title="New experiment">
            <form className="flex flex-col gap-3" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
              <Field id="ek" label="Key" hint="lowercase-with-dashes"><Input id="ek" value={f.key} onChange={(e) => setF({ ...f, key: e.target.value })} /></Field>
              <Field id="eh" label="Hypothesis" hint="Write it before starting."><Textarea id="eh" value={f.hypothesis} onChange={(e) => setF({ ...f, hypothesis: e.target.value })} /></Field>
              <Field id="ev" label="Variants"><Select id="ev" value={f.variants} onChange={(e) => setF({ ...f, variants: e.target.value })}><option value="lexical,rrf">lexical (control), hybrid rrf</option><option value="rrf,lexical">hybrid rrf (control), lexical</option></Select></Field>
              <Field id="em" label="Minimum accounts per variant"><Input id="em" type="number" min={10} value={f.min} onChange={(e) => setF({ ...f, min: e.target.value })} /></Field>
              {create.error ? <Notice tone="danger">{create.error.detail}</Notice> : null}
              <Button type="submit" variant="primary" busy={create.isPending}>Save draft</Button>
            </form>
          </Card>
        ) : null}
      </div>
    </div>
  );
}
