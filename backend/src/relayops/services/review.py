"""Version-bound proposals and reviews.

A review approves an exact binding: scope, reviewer, ticket revision, proposal version, action kind,
destination, payload hash, evidence snapshot hash, and policy version. Editing creates a new proposal
version and supersedes the old one, so its approval can no longer apply.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from relayops.agents import verification
from relayops.core.config import get_settings
from relayops.core.security import content_hash
from relayops.domain.binding import approval_binding, binding_hash, binding_mismatches
from relayops.domain.policies import POLICY_VERSION
from relayops.domain.scope import Conflict, Principal, ValidationFailed
from relayops.models import InvestigationRun, Job, Proposal, Review, Ticket
from relayops.repositories import scoped
from relayops.services import artifacts, audit


def evidence_hash(evidence: list[dict[str, Any]]) -> str:
    return content_hash(sorted(e["snapshot_hash"] for e in evidence))


def create_proposal(
    db: Session,
    run: InvestigationRun,
    *,
    route: str,
    action_kind: str,
    destination: dict[str, Any],
    payload: dict[str, Any],
    evidence: dict[str, dict[str, Any]],
    context: dict[str, Any],
    authored_by: str = "agent",
    version: int = 1,
    claim_provider: Any | None = None,
    claim_verifier_info: dict[str, Any] | None = None,
) -> Proposal:
    """Idempotent on (run, version): re-executing the node after a crash returns the same row."""
    existing = db.execute(
        select(Proposal).where(Proposal.run_id == run.id, Proposal.version == version)
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    ver = verification.verify(
        db,
        organization_id=run.organization_id,
        customer_account_id=run.customer_account_id,
        action_kind=action_kind,
        payload=payload,
        evidence=evidence,
        context=context,
        claim_provider=claim_provider,
        claim_verifier_info=claim_verifier_info,
        claim_timeout=get_settings().claim_verifier_timeout_seconds,
        claim_note=None
        if authored_by == "agent"
        else "edited by a reviewer; the semantic verifier does not run on "
        "human edits, so the reviewer's own review is the semantic check",
    )
    used = set(payload.get("reply_evidence_ids") or []) | set(payload.get("internal_evidence_ids") or [])
    ev_list = [{"id": k, **v} for k, v in evidence.items() if k in used]
    prop = Proposal(
        data_class=run.data_class,
        run_id=run.id,
        organization_id=run.organization_id,
        customer_account_id=run.customer_account_id,
        ticket_id=run.ticket_id,
        version=version,
        route=route,
        action_kind=action_kind,
        destination=destination,
        payload=payload,
        payload_hash=content_hash(payload),
        evidence=ev_list,
        evidence_hash=evidence_hash(ev_list),
        policy_version=run.policy_version,
        ticket_revision=run.ticket_revision,
        verification=ver,
        verification_status=ver["status"],
        status="pending_review",
        authored_by=authored_by,
    )
    db.add(prop)
    db.flush()
    art = artifacts.for_proposal(db, prop)
    art.proposal_id = prop.id if version == 1 else art.proposal_id
    artifacts.add_version(
        db,
        art,
        content=payload.get("customer_reply", ""),
        sources=ev_list,
        verification=ver,
        created_by=authored_by,
        note=f"proposal v{version}",
    )
    artifacts.engineering_brief(db, prop, authored_by)
    return prop


def _current_binding(db: Session, prop: Proposal, reviewer_id: str) -> dict[str, Any]:
    ticket = db.get(Ticket, prop.ticket_id)
    assert ticket is not None
    return approval_binding(
        organization_id=prop.organization_id,
        customer_account_id=prop.customer_account_id,
        reviewer_user_id=reviewer_id,
        ticket_id=prop.ticket_id,
        ticket_revision=ticket.revision,
        proposal_id=prop.id,
        proposal_version=prop.version,
        action_kind=prop.action_kind,
        destination=prop.destination,
        payload_hash=content_hash(prop.payload),
        evidence_hash=prop.evidence_hash,
        policy_version=POLICY_VERSION,
    )


def _proposal_binding(prop: Proposal, reviewer_id: str) -> dict[str, Any]:
    return approval_binding(
        organization_id=prop.organization_id,
        customer_account_id=prop.customer_account_id,
        reviewer_user_id=reviewer_id,
        ticket_id=prop.ticket_id,
        ticket_revision=prop.ticket_revision,
        proposal_id=prop.id,
        proposal_version=prop.version,
        action_kind=prop.action_kind,
        destination=prop.destination,
        payload_hash=prop.payload_hash,
        evidence_hash=prop.evidence_hash,
        policy_version=prop.policy_version,
    )


def staleness(db: Session, prop: Proposal) -> list[str]:
    """Reasons an approval of this proposal would no longer match the world (empty means fresh)."""
    reasons = binding_mismatches(_proposal_binding(prop, ""), _current_binding(db, prop, ""))
    run = db.get(InvestigationRun, prop.run_id)
    assert run is not None
    evidence = {e["id"]: e for e in prop.evidence}
    recheck = verification.verify(
        db,
        organization_id=prop.organization_id,
        customer_account_id=prop.customer_account_id,
        action_kind=prop.action_kind,
        payload=prop.payload,
        evidence=evidence,
        context=prop.payload["context_snapshot"],
    )
    if "source_currency" in recheck["failed"]:
        reasons.append("source_currency")
    return reasons


def _lock_pending(
    db: Session, p: Principal, proposal_id: str, expected_version: int | None, expected_payload_hash: str | None
) -> Proposal:
    scoped.require_staff(p)
    prop = scoped.get_proposal(db, p, proposal_id, for_update=True)
    run = db.get(InvestigationRun, prop.run_id)
    assert run is not None
    if run.mode != "live":
        raise Conflict("recorded replays cannot be reviewed or executed")
    if run.status == "cancelled":
        raise Conflict("the investigation was cancelled")
    if prop.status != "pending_review":
        raise Conflict(f"proposal is {prop.status}; only the latest pending version can be reviewed")
    if expected_version is not None and expected_version != prop.version:
        raise Conflict("proposal version changed; reload before reviewing")
    if expected_payload_hash is not None and expected_payload_hash != prop.payload_hash:
        raise Conflict("proposal content changed; reload before reviewing")
    ticket = db.get(Ticket, prop.ticket_id)
    if ticket is not None and ticket.restricted and not p.is_admin:
        raise scoped.AccessDenied("restricted security tickets require an admin reviewer")
    return prop


def edit_proposal(
    db: Session, p: Principal, proposal_id: str, *, customer_reply: str, expected_version: int, note: str | None = None
) -> Proposal:
    prop = _lock_pending(db, p, proposal_id, expected_version, None)
    text = customer_reply.strip()
    if len(text) < 10:
        raise ValidationFailed("reply must be at least 10 characters")
    if text == (prop.payload.get("customer_reply") or "").strip():
        raise ValidationFailed("no changes to save")
    run = db.get(InvestigationRun, prop.run_id)
    assert run is not None
    payload = {**prop.payload, "customer_reply": text, "edited_by": p.user_id}
    evidence = {e["id"]: {k: v for k, v in e.items() if k != "id"} for e in prop.evidence}
    prop.status = "superseded"
    db.flush()
    new = create_proposal(
        db,
        run,
        route=prop.route,
        action_kind=prop.action_kind,
        destination=prop.destination,
        payload=payload,
        evidence=evidence,
        context=prop.payload["context_snapshot"],
        authored_by=p.user_id,
        version=prop.version + 1,
    )
    # A new customer message may have arrived since the run started; the edit is made against today's ticket.
    ticket = db.get(Ticket, prop.ticket_id)
    assert ticket is not None
    new.ticket_revision = ticket.revision
    audit.record(
        db,
        organization_id=p.organization_id,
        actor=p,
        action="proposal.edited",
        target_type="proposal",
        target_id=new.id,
        detail={
            "from_version": prop.version,
            "to_version": new.version,
            "payload_hash": new.payload_hash,
            "verification": new.verification_status,
            "note": note,
        },
    )
    from relayops.services.runs import _emit

    _emit(
        db,
        run,
        "proposal_edited",
        "review",
        {"proposal_id": new.id, "version": new.version, "verification": new.verification_status, "by": p.user_id},
    )
    return new


def approve(
    db: Session,
    p: Principal,
    proposal_id: str,
    *,
    expected_version: int,
    expected_payload_hash: str,
    note: str | None = None,
    acknowledge_uncertain_claims: bool = False,
) -> Review:
    prop = _lock_pending(db, p, proposal_id, expected_version, expected_payload_hash)
    if prop.verification_status != "passed":
        raise Conflict("verification has not passed for this version; edit the draft or reject it")
    uncertain = int(prop.verification.get("uncertain_claims") or 0)
    if uncertain and not acknowledge_uncertain_claims:
        raise Conflict(f"{uncertain} claim(s) could not be confirmed from cited sources; confirm you checked them")
    stale = staleness(db, prop)
    if stale:
        raise Conflict("proposal is stale (" + ", ".join(stale) + "); start a new run or edit to refresh it")
    binding = _current_binding(db, prop, p.user_id)
    review = Review(
        proposal_id=prop.id,
        organization_id=prop.organization_id,
        reviewer_user_id=p.user_id,
        decision="approve",
        binding=binding,
        binding_hash=binding_hash(binding),
        note=note,
    )
    db.add(review)
    prop.status = "approved"
    db.flush()
    db.add(
        Job(
            organization_id=prop.organization_id,
            run_id=prop.run_id,
            kind="resume",
            dedupe_key=f"resume:{prop.run_id}:{prop.id}",
            payload={"decision": "approve", "proposal_id": prop.id, "review_id": review.id},
        )
    )
    audit.record(
        db,
        organization_id=p.organization_id,
        actor=p,
        action="proposal.approved",
        target_type="proposal",
        target_id=prop.id,
        detail={
            "binding_hash": review.binding_hash,
            "version": prop.version,
            "action_kind": prop.action_kind,
            "uncertain_claims_acknowledged": uncertain if acknowledge_uncertain_claims else 0,
        },
    )
    return review


def reject(db: Session, p: Principal, proposal_id: str, *, expected_version: int, note: str | None) -> Review:
    prop = _lock_pending(db, p, proposal_id, expected_version, None)
    binding = _current_binding(db, prop, p.user_id)
    review = Review(
        proposal_id=prop.id,
        organization_id=prop.organization_id,
        reviewer_user_id=p.user_id,
        decision="reject",
        binding=binding,
        binding_hash=binding_hash(binding),
        note=note,
    )
    db.add(review)
    prop.status = "rejected"
    db.flush()
    db.add(
        Job(
            organization_id=prop.organization_id,
            run_id=prop.run_id,
            kind="resume",
            dedupe_key=f"resume:{prop.run_id}:{prop.id}",
            payload={"decision": "reject", "proposal_id": prop.id, "review_id": review.id},
        )
    )
    audit.record(
        db,
        organization_id=p.organization_id,
        actor=p,
        action="proposal.rejected",
        target_type="proposal",
        target_id=prop.id,
        detail={"version": prop.version, "note": note},
    )
    return review


def verify_binding_for_execution(db: Session, prop: Proposal, review: Review) -> list[str]:
    """Recheck right before executing: the approved binding must still equal current state."""
    if review.decision != "approve" or review.proposal_id != prop.id:
        return ["review_mismatch"]
    if binding_hash(review.binding) != review.binding_hash:
        return ["binding_tampered"]
    return binding_mismatches(review.binding, _current_binding(db, prop, review.reviewer_user_id))
