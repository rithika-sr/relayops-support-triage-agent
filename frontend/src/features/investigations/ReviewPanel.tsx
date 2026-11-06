"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, Button, Field, Mono, Notice, StatusBadge, Textarea } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { fmtDate, label, shortHash } from "@/lib/format";
import type { Proposal } from "@/lib/types";

const CLAIM_TONE: Record<string, "teal" | "amber"> = { provenance_checked: "teal", semantically_unverified: "amber" };

export function ReviewPanel({ proposal, runId, ticketId, canReview, onSelectEvidence }: {
  proposal: Proposal;
  runId: string;
  ticketId?: string;
  canReview: boolean;
  onSelectEvidence?: (id: string) => void;
}) {
  const qc = useQueryClient();
  const [draft, setDraft] = useState(proposal.payload.customer_reply);
  const [note, setNote] = useState("");
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["run", runId] });
    if (ticketId) qc.invalidateQueries({ queryKey: ["ticket", ticketId] });
  };
  const edit = useMutation<Proposal, ApiError>({
    mutationFn: () => api.post(`/proposals/${proposal.id}/edit`, { customer_reply: draft, expected_version: proposal.version, note: note || null }),
    onSuccess: refresh,
  });
  const approve = useMutation<unknown, ApiError>({
    mutationFn: () => api.post(`/proposals/${proposal.id}/approve`, { expected_version: proposal.version, expected_payload_hash: proposal.payload_hash, note: note || null }),
    onSuccess: refresh,
  });
  const reject = useMutation<unknown, ApiError>({
    mutationFn: () => api.post(`/proposals/${proposal.id}/reject`, { expected_version: proposal.version, note: note || null }),
    onSuccess: refresh,
  });
  const pending = proposal.status === "pending_review";
  const dirty = draft.trim() !== proposal.payload.customer_reply.trim();
  const stale = proposal.stale_reasons.length > 0;
  const failed = proposal.verification_status !== "passed";
  const err = edit.error ?? approve.error ?? reject.error;
  const p = proposal.payload;
  const approveBlocked = !canReview ? "Your role cannot review this ticket." : dirty ? "Save your edit first; approval applies to a saved version." : stale ? `Stale: ${proposal.stale_reasons.join(", ")}.` : failed ? "Verification has not passed for this version." : null;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="ink">v{proposal.version}</Badge>
        <StatusBadge status={proposal.status} />
        <Badge tone="teal">{label(proposal.route)}</Badge>
        <Badge>{label(proposal.action_kind)}</Badge>
        <span className="text-xs text-muted">ticket rev {proposal.ticket_revision} · policy {proposal.policy_version} · payload <Mono title={proposal.payload_hash}>{shortHash(proposal.payload_hash)}</Mono></span>
      </div>
      {p.rationale ? <p className="text-sm"><span className="font-medium">Rationale:</span> {p.rationale}</p> : null}
      {p.overrides?.length ? <Notice tone="amber">Code constraints applied: {p.overrides.join("; ")}</Notice> : null}
      {p.verdict && p.verdict !== "proposed" ? <Notice tone="amber">Verdict: {label(p.verdict)}. Completing this task does not mean the answer is correct.</Notice> : null}
      {stale && pending ? <Notice tone="danger">This draft no longer matches current state ({proposal.stale_reasons.join(", ")}). Approval is blocked; edit to refresh it against the current ticket or start a new run.</Notice> : null}

      <section aria-labelledby="dest">
        <h3 id="dest" className="text-sm font-semibold">Destination (local, no email)</h3>
        <p className="text-sm text-muted">
          Customer-visible reply on ticket thread
          {proposal.destination.engineering ? ` · new local engineering handoff to ${(proposal.destination.engineering as { team: string }).team}` : ""}
          {p.issue_key && proposal.action_kind === "link_engineering_issue" ? ` · link to ${p.issue_key}` : ""}
          {proposal.destination.incident_id ? ` · link to incident ${String(proposal.destination.incident_id)}` : ""}
        </p>
      </section>

      <form onSubmit={(e) => { e.preventDefault(); edit.mutate(); }} className="flex flex-col gap-2">
        <Field id="reply-draft" label="Customer reply draft" hint={`Source: ${p.reply_source ?? "model"}. Cites ${p.reply_evidence_ids.join(", ") || "no evidence"}.`}>
          <Textarea id="reply-draft" value={draft} onChange={(e) => setDraft(e.target.value)} readOnly={!pending || !canReview} className="min-h-40" />
        </Field>
        <Field id="review-note" label="Review note (optional)">
          <Textarea id="review-note" value={note} onChange={(e) => setNote(e.target.value)} className="min-h-12" readOnly={!pending || !canReview} />
        </Field>
        {err ? <Notice tone="danger">{err.detail}</Notice> : null}
        {pending ? (
          <div className="flex flex-wrap items-center gap-2">
            <Button type="submit" disabled={!dirty || !canReview} busy={edit.isPending} title={!dirty ? "No changes to save" : undefined}>Save edit as v{proposal.version + 1}</Button>
            <Button type="button" variant="primary" disabled={!!approveBlocked} busy={approve.isPending} onClick={() => approve.mutate()} title={approveBlocked ?? undefined}>
              Approve v{proposal.version}
            </Button>
            <Button type="button" variant="danger" disabled={!canReview} busy={reject.isPending} onClick={() => reject.mutate()}>Reject</Button>
            {approveBlocked ? <span className="text-xs text-muted">{approveBlocked}</span> : null}
          </div>
        ) : null}
      </form>

      <section aria-labelledby="checks">
        <h3 id="checks" className="text-sm font-semibold">Verification · <StatusBadge status={proposal.verification_status} /></h3>
        <ul className="mt-1 flex flex-col gap-1 text-sm">
          {proposal.verification.checks.map((c) => (
            <li key={c.name} className="flex gap-2"><StatusBadge status={c.status} /><span><span className="font-medium">{label(c.name)}</span> <span className="text-muted">({c.method}) {c.detail}</span></span></li>
          ))}
        </ul>
        <p className="mt-2 text-xs text-muted">{proposal.verification.note}</p>
      </section>

      {proposal.verification.claims?.length ? (
        <section aria-labelledby="claims">
          <h3 id="claims" className="text-sm font-semibold">Claims in the reply</h3>
          <ul className="mt-1 flex flex-col gap-1 text-sm">
            {proposal.verification.claims.map((c, i) => (
              <li key={i} className="flex gap-2">
                <Badge tone={CLAIM_TONE[c.label] ?? "neutral"} title={`lexical overlap ${c.lexical_overlap}`}>{label(c.label)}</Badge>
                <span>{c.text}</span>
              </li>
            ))}
          </ul>
          <p className="mt-1 text-xs text-muted">Lexical overlap with cited sources is shown as a signal only; it is not proof the source supports the claim. Human review is the semantic check.</p>
        </section>
      ) : null}

      {p.observations?.length || p.hypotheses?.length || p.missing_facts?.length ? (
        <section className="grid gap-3 sm:grid-cols-3 text-sm">
          <div><h3 className="font-semibold">Observations</h3><ul className="list-disc pl-4">{p.observations?.map((o, i) => <li key={i}>{o}</li>)}</ul></div>
          <div><h3 className="font-semibold">Hypotheses <span className="font-normal text-muted">(unconfirmed)</span></h3><ul className="list-disc pl-4">{p.hypotheses?.map((o, i) => <li key={i}>{o}</li>)}</ul></div>
          <div><h3 className="font-semibold">Missing facts</h3><ul className="list-disc pl-4">{p.missing_facts?.map((o, i) => <li key={i}>{o}</li>)}</ul></div>
        </section>
      ) : null}

      {p.handoff ? (
        <section className="rounded-md border border-line p-3 text-sm">
          <h3 className="font-semibold">Engineering handoff draft</h3>
          <p className="mt-1 font-medium">{String(p.handoff.title)}</p>
          <p className="text-muted">{String(p.handoff.summary ?? "")}</p>
          <p className="mt-1 text-xs text-muted">Owner: {String(p.handoff.team)} · component {String(p.handoff.component)}</p>
        </section>
      ) : null}

      {p.computed_facts ? (
        <section className="text-sm">
          <h3 className="font-semibold">Computed facts (from records)</h3>
          <dl className="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs">
            {Object.entries(p.computed_facts).filter(([k]) => k !== "entitlements").map(([k, v]) => (
              <div key={k} className="contents"><dt className="text-muted">{label(k)}</dt><dd>{String(v ?? "—")}</dd></div>
            ))}
          </dl>
        </section>
      ) : null}

      {proposal.evidence.length && onSelectEvidence ? (
        <p className="text-xs text-muted">Evidence used: {proposal.evidence.map((e) => (
          <button key={e.id} className="mr-1 font-mono text-teal-700 underline" onClick={() => onSelectEvidence(e.id)}>{e.id}</button>
        ))}</p>
      ) : null}

      {proposal.reviews.length ? (
        <section className="text-sm">
          <h3 className="font-semibold">Review history</h3>
          <ul>{proposal.reviews.map((r) => (
            <li key={r.id}>{r.decision} by {r.reviewer} · {fmtDate(r.created_at)} · binding <Mono title={r.binding_hash}>{shortHash(r.binding_hash)}</Mono>{r.note ? ` · “${r.note}”` : ""}</li>
          ))}</ul>
        </section>
      ) : null}
    </div>
  );
}
