"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, Button, Disclosure, Field, Notice, StatusBadge, Textarea, useToast } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { fmtDate, label } from "@/lib/format";
import type { Check, Claim, Proposal } from "@/lib/types";

const GROUPS: { id: string; title: string; checks: string[] }[] = [
  { id: "provenance", title: "Provenance checked", checks: ["required_fields", "provenance", "reply_visibility", "source_currency"] },
  { id: "policy", title: "Policy checked", checks: ["entitlement_sso", "no_internal_disclosure", "no_unsupported_root_cause", "no_unconfirmed_outage", "issue_link", "incident_link", "incident_visibility", "typed_facts"] },
];

export function routeSentence(p: Proposal): string {
  const issue = p.payload.issue_key;
  switch (p.route) {
    case "link_existing_issue": return `Reply to the customer and link the ticket to known issue ${issue ?? ""}.`;
    case "new_engineering_handoff": return `Reply to the customer and hand off to ${String(p.payload.handoff?.team ?? "engineering")} as a new local engineering record.`;
    case "feature_request": return issue ? `Reply and record the request on ${issue}.` : "Reply and record a new feature request.";
    case "incident_link": return "Reply with the approved incident summary and link the ticket to the reviewed incident.";
    case "clarification": return "Ask the customer for the missing details before acting.";
    case "specialist_review": return "Acknowledge the customer and route the ticket to restricted specialist review.";
    default: return "Reply to the customer.";
  }
}

function consequences(p: Proposal): string[] {
  const out = ["Posts exactly this text to the customer's ticket thread in RelayOps. No email is sent."];
  if (p.action_kind === "link_engineering_issue") out.push(`Links this ticket to ${p.payload.issue_key ?? "the issue"} (local record).`);
  if (p.action_kind === "create_engineering_handoff") out.push("Creates a new local engineering issue with the handoff details.");
  if (p.action_kind === "link_incident") out.push("Links this ticket to the reviewed incident.");
  if (p.action_kind === "escalate_specialist") out.push("Marks the ticket restricted and queues it for specialist review.");
  out.push("The ticket then waits on the customer; it is not marked resolved.");
  return out;
}

function lineDiff(before: string, after: string): { kind: "same" | "add" | "del"; text: string }[] {
  const a = before.split(/(?<=[.!?])\s+|\n/).filter(Boolean);
  const b = after.split(/(?<=[.!?])\s+|\n/).filter(Boolean);
  const setA = new Set(a);
  const setB = new Set(b);
  return [...a.filter((x) => !setB.has(x)).map((text) => ({ kind: "del" as const, text })),
    ...b.map((text) => ({ kind: setA.has(text) ? ("same" as const) : ("add" as const), text }))];
}

function groupStatus(checks: Check[]): "pass" | "warn" | "fail" | "none" {
  if (!checks.length) return "none";
  if (checks.some((c) => c.status === "fail")) return "fail";
  if (checks.some((c) => c.status === "warn")) return "warn";
  return "pass";
}

const CLAIM_TONE: Record<string, "ok" | "danger" | "neutral" | "warn"> = {
  supported: "ok", contradicted: "danger", insufficient_evidence: "warn", unavailable: "warn", not_a_claim: "neutral",
};
const VERDICT_TEXT: Record<string, string> = {
  supported: "Supported", contradicted: "Contradicted", insufficient_evidence: "Not in sources", unavailable: "Not checked",
};
const METHOD_TEXT: Record<string, string> = {
  typed_entitlement: "plan record", typed_number: "number in cited source", semantic_model: "local model judgment",
  not_run: "no automatic check", none: "",
};

export function ReviewPanel({ proposal, previous, runId, ticketId, canReview, onSelectEvidence }: {
  proposal: Proposal;
  previous?: Proposal;
  runId: string;
  ticketId?: string;
  canReview: boolean;
  onSelectEvidence?: (id: string) => void;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const [draft, setDraft] = useState(proposal.payload.customer_reply);
  const [note, setNote] = useState("");
  const [ack, setAck] = useState(false);
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["run", runId] });
    if (ticketId) qc.invalidateQueries({ queryKey: ["ticket", ticketId] });
  };
  const edit = useMutation<Proposal, ApiError>({
    mutationFn: () => api.post(`/proposals/${proposal.id}/edit`, { customer_reply: draft, expected_version: proposal.version, note: note || null }),
    onSuccess: () => { toast(`Saved as version ${proposal.version + 1}; checks re-ran on the new text.`); refresh(); },
  });
  const approve = useMutation<unknown, ApiError>({
    mutationFn: () => api.post(`/proposals/${proposal.id}/approve`, { expected_version: proposal.version, expected_payload_hash: proposal.payload_hash, note: note || null, acknowledge_uncertain_claims: ack }),
    onSuccess: () => { toast("Approved. Publishing runs once in the background."); refresh(); },
  });
  const reject = useMutation<unknown, ApiError>({
    mutationFn: () => api.post(`/proposals/${proposal.id}/reject`, { expected_version: proposal.version, note: note || null }),
    onSuccess: () => { toast("Rejected. Nothing was sent.", "neutral"); refresh(); },
  });
  const pending = proposal.status === "pending_review";
  const dirty = draft.trim() !== proposal.payload.customer_reply.trim();
  const stale = proposal.stale_reasons.length > 0;
  const failed = proposal.verification_status !== "passed";
  const err = edit.error ?? approve.error ?? reject.error;
  const p = proposal.payload;
  const checks = proposal.verification.checks ?? [];
  const claims = proposal.verification.claims ?? [];
  const substantive = claims.filter((c) => c.kind === "factual" || c.kind === "procedural");
  const uncertain = substantive.filter((c) => c.verdict === "insufficient_evidence" || c.verdict === "unavailable");
  const contradicted = claims.filter((c) => c.verdict === "contradicted");
  const needsAck = uncertain.length > 0;
  const approveBlocked = !canReview ? "Your role cannot review this ticket." : dirty ? "Save your edit first; approval applies to a saved version."
    : stale ? `This draft is out of date (${proposal.stale_reasons.join(", ")}).` : failed ? "Fix the failed checks before approving."
    : needsAck && !ack ? "Confirm you checked the uncertain claims." : null;
  const verifier = proposal.verification.claim_verifier;
  const labels = useQuery({
    queryKey: ["claim-labels", proposal.id],
    queryFn: () => api.get<LabelRow[]>(`/proposals/${proposal.id}/annotations`),
    enabled: canReview,
  });
  const primaryLabel = proposal.action_kind === "create_engineering_handoff" ? "Approve reply and create handoff" : "Approve and publish reply";
  const human = proposal.reviews.find((r) => r.decision === "approve");

  return (
    <div className="flex flex-col gap-5">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-semibold">Proposed response</h2>
          <StatusBadge status={proposal.status} />
          <span className="text-[13px] text-muted">version {proposal.version}</span>
        </div>
        <p className="mt-1 text-sm">{routeSentence(proposal)}</p>
        {p.rationale ? <p className="mt-1 text-[13px] text-muted">Why: {p.rationale}</p> : null}
      </div>

      {stale && pending ? <Notice tone="danger" title="This draft is out of date">{`Changed since it was drafted: ${proposal.stale_reasons.join(", ")}. Edit it (which re-checks against the current ticket) or start a new investigation.`}</Notice> : null}
      {p.overrides?.length ? <Notice tone="warn" title="Adjusted by policy">{p.overrides.join("; ")}</Notice> : null}

      <Field id="reply-draft" label="Customer will see exactly this" hint={pending && canReview ? "Editing creates a new version and re-runs every check." : undefined}>
        <Textarea id="reply-draft" value={draft} onChange={(e) => setDraft(e.target.value)} readOnly={!pending || !canReview} className="min-h-44 text-[15px] leading-relaxed" />
      </Field>

      {previous ? (
        <Disclosure summary={`Changes from version ${previous.version}`}>
          <ul className="flex flex-col gap-1 text-sm">
            {lineDiff(previous.payload.customer_reply, proposal.payload.customer_reply).filter((l) => l.kind !== "same").map((l, i) => (
              <li key={i} className={l.kind === "add" ? "rounded bg-ok-50 px-2 py-0.5 text-ok-700" : "rounded bg-danger-50 px-2 py-0.5 text-danger-700 line-through"}>
                <span className="sr-only">{l.kind === "add" ? "Added: " : "Removed: "}</span>{l.text}
              </li>
            ))}
          </ul>
        </Disclosure>
      ) : null}

      <section aria-labelledby="checks-h" className="rounded-lg border border-line">
        <h3 id="checks-h" className="border-b border-line px-4 py-2.5 text-sm font-semibold">Review status</h3>
        <ul className="divide-y divide-line text-sm">
          {GROUPS.map((g) => {
            const items = checks.filter((c) => g.checks.includes(c.name));
            const st = groupStatus(items);
            return (
              <li key={g.id}>
                <details>
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-4 py-2.5">
                    <span>{g.title}</span>
                    <StatusBadge status={st === "none" ? null : st} />
                  </summary>
                  <ul className="flex flex-col gap-1.5 px-4 pb-3">
                    {items.map((c) => (
                      <li key={c.name} className="flex gap-2"><StatusBadge status={c.status} /><span><span className="font-medium">{label(c.name)}</span> <span className="text-muted">{c.detail}</span></span></li>
                    ))}
                  </ul>
                </details>
              </li>
            );
          })}
          <li>
            <details>
              <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-4 py-2.5">
                <span>Claim support</span>
                <span>
                  {contradicted.length ? <Badge tone="danger">{contradicted.length} contradicted</Badge>
                    : uncertain.length ? <Badge tone="warn">{uncertain.length} of {substantive.length} uncertain</Badge>
                    : <Badge tone="ok">{substantive.length ? "all claims supported" : "no factual claims"}</Badge>}
                </span>
              </summary>
              <div className="px-4 pb-3">
                <ul className="flex flex-col gap-2">
                  {claims.map((c, i) => (
                    <li key={i} className="flex gap-2">
                      <Badge tone={CLAIM_TONE[c.verdict] ?? "warn"}>{VERDICT_TEXT[c.verdict] ?? label(c.kind)}</Badge>
                      <span>
                        {c.text}
                        {c.method !== "none" ? (
                          <span className="block text-xs text-muted">
                            {METHOD_TEXT[c.method]}{c.evidence_ids.length ? ` · ${c.evidence_ids.join(", ")}` : ""}{c.detail ? ` · ${c.detail}` : ""}
                          </span>
                        ) : null}
                        {canReview && (c.kind === "factual" || c.kind === "procedural" || c.kind === "hypothesis") ? (
                          <ClaimLabel proposalId={proposal.id} index={i} claim={c} human={labels.data?.find((l) => l.claim_index === i)} />
                        ) : null}
                      </span>
                    </li>
                  ))}
                </ul>
                <p className="mt-2 text-xs text-muted">
                  {proposal.verification.note}
                  {verifier?.kind === "local_model" ? ` Verifier: ${verifier.model}${verifier.digest ? ` (${verifier.digest.slice(0, 12)})` : ""}.` : ""}
                </p>
              </div>
            </details>
          </li>
          <li className="flex items-center justify-between gap-2 px-4 py-2.5">
            <span>Human reviewed</span>
            {human ? <Badge tone="ok">approved by {human.reviewer}</Badge> : <Badge>not yet</Badge>}
          </li>
        </ul>
      </section>

      {p.missing_facts?.length || p.hypotheses?.length ? (
        <section className="grid gap-3 text-sm sm:grid-cols-2">
          {p.missing_facts?.length ? <div><h3 className="font-semibold">Still unknown</h3><ul className="mt-1 list-disc pl-5">{p.missing_facts.map((o, i) => <li key={i}>{label(o)}</li>)}</ul></div> : null}
          {p.hypotheses?.length ? <div><h3 className="font-semibold">Unconfirmed hypotheses</h3><ul className="mt-1 list-disc pl-5 text-muted">{p.hypotheses.map((o, i) => <li key={i}>{o}</li>)}</ul></div> : null}
        </section>
      ) : null}

      {p.handoff ? (
        <Disclosure summary="Engineering handoff details">
          <p className="font-medium">{String(p.handoff.title)}</p>
          <p className="mt-1 text-sm text-muted">{String(p.handoff.summary ?? "")}</p>
          <p className="mt-1 text-xs text-muted">Owner: {String(p.handoff.team)} · component {String(p.handoff.component)}</p>
        </Disclosure>
      ) : null}

      {proposal.evidence.length && onSelectEvidence ? (
        <p className="text-[13px] text-muted">Sources used: {proposal.evidence.map((e) => (
          <button key={e.id} className="mr-1.5 text-accent-700 underline" onClick={() => onSelectEvidence(e.id)}>{e.title.slice(0, 40)}</button>
        ))}</p>
      ) : null}

      {proposal.reviews.length ? (
        <p className="text-[13px] text-muted">History: {proposal.reviews.map((r) => `${r.decision} by ${r.reviewer} ${fmtDate(r.created_at)}${r.note ? ` (“${r.note}”)` : ""}`).join("; ")}</p>
      ) : null}

      {pending ? (
        <div className="sticky bottom-0 -mx-5 flex flex-col gap-3 border-t border-line bg-card px-5 py-3">
          <div className="rounded-md bg-sunken px-3 py-2 text-[13px]">
            <p className="font-medium">If you approve</p>
            <ul className="list-disc pl-5 text-muted">{consequences(proposal).map((c) => <li key={c}>{c}</li>)}</ul>
          </div>
          <Field id="review-note" label="Note for the history (optional)">
            <Textarea id="review-note" value={note} onChange={(e) => setNote(e.target.value)} className="min-h-10" readOnly={!canReview} />
          </Field>
          {needsAck && !failed ? (
            <label className="flex items-start gap-2 text-sm">
              <input type="checkbox" className="mt-1" checked={ack} onChange={(e) => setAck(e.target.checked)} disabled={!canReview} />
              <span>I checked the {uncertain.length} claim{uncertain.length === 1 ? "" : "s"} the sources could not confirm.</span>
            </label>
          ) : null}
          {err ? <Notice tone="danger">{err.detail}</Notice> : null}
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="primary" disabled={!!approveBlocked} busy={approve.isPending} onClick={() => approve.mutate()} title={approveBlocked ?? undefined}>{primaryLabel}</Button>
            <Button disabled={!dirty || !canReview} busy={edit.isPending} onClick={() => edit.mutate()}>Save edit as version {proposal.version + 1}</Button>
            <Button variant="danger" disabled={!canReview} busy={reject.isPending} onClick={() => reject.mutate()}>Reject</Button>
          </div>
          {approveBlocked ? <p className="text-[13px] text-muted">{approveBlocked}</p> : null}
        </div>
      ) : null}
    </div>
  );
}

interface LabelRow { claim_index: number; consensus: string; labels: { annotator: string; verdict: string }[] }

function ClaimLabel({ proposalId, index, claim, human }: { proposalId: string; index: number; claim: Claim; human?: LabelRow }) {
  const qc = useQueryClient();
  const save = useMutation<unknown, ApiError, string>({
    mutationFn: (verdict) => api.post(`/proposals/${proposalId}/claims/${index}/annotations`, { verdict, claim_sha256: claim.sha256 }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["claim-labels", proposalId] }); qc.invalidateQueries({ queryKey: ["label-stats"] }); },
  });
  const id = `claim-label-${proposalId}-${index}`;
  return (
    <span className="mt-1 flex flex-wrap items-center gap-2 text-xs">
      <label htmlFor={id} className="text-muted">Your label</label>
      <select id={id} className="rounded border border-line bg-card px-1.5 py-0.5" value="" disabled={save.isPending || !claim.sha256}
        onChange={(e) => e.target.value && save.mutate(e.target.value)}>
        <option value="">{human ? "Change…" : "Choose…"}</option>
        <option value="supported">Supported by sources</option>
        <option value="contradicted">Contradicted by sources</option>
        <option value="insufficient_evidence">Not in sources</option>
      </select>
      {human ? <span className="text-muted">Human: {human.consensus === "disagreement" ? "annotators disagree" : label(human.consensus)} ({human.labels.length})</span> : null}
      {save.error ? <span className="text-danger-700">{save.error.detail}</span> : null}
    </span>
  );
}
