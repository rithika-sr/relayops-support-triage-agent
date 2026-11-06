"""Approved action execution with a unique action ledger and a transactional outbox.

Default mode is local: an approved reply becomes a customer-visible message in this application (not an
email), and an approved handoff creates or links a local engineering record. External adapters are
disabled; a deterministic simulated adapter exists to test failure semantics. An ambiguous remote outcome
is recorded as `unknown` and reconciled by marker lookup, never blindly recreated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from relayops.core.clock import utcnow
from relayops.domain.routes import ActionKind
from relayops.models import (
    ActionRecord,
    Artifact,
    EngineeringIssue,
    IncidentTicketLink,
    OutboxMessage,
    Proposal,
    Review,
    Ticket,
    TicketIssueLink,
    TicketMessage,
)
from relayops.services import audit
from relayops.services.review import verify_binding_for_execution


class ActionRefused(Exception):
    pass


def idempotency_key(prop: Proposal) -> str:
    return f"{prop.id}:{prop.payload_hash}"


def execute(db: Session, proposal_id: str, review_id: str) -> ActionRecord:
    """Execute one approved proposal exactly once. Safe to call repeatedly (resume after crash)."""
    prop = db.execute(select(Proposal).where(Proposal.id == proposal_id).with_for_update()).scalar_one()
    existing = db.execute(select(ActionRecord).where(ActionRecord.proposal_id == prop.id)).scalar_one_or_none()
    if existing is not None:
        return existing
    review = db.get(Review, review_id)
    if review is None or prop.status != "approved":
        raise ActionRefused("proposal is not approved")
    ticket = db.execute(select(Ticket).where(Ticket.id == prop.ticket_id).with_for_update()).scalar_one()
    mismatches = verify_binding_for_execution(db, prop, review)
    if mismatches:
        prop.status = "stale"
        audit.record(
            db,
            organization_id=prop.organization_id,
            action="action.refused_stale",
            target_type="proposal",
            target_id=prop.id,
            actor_kind="system",
            outcome="failed",
            detail={"mismatches": mismatches},
        )
        raise ActionRefused("approval no longer matches current state: " + ", ".join(mismatches))

    now = utcnow()
    record = ActionRecord(
        organization_id=prop.organization_id,
        customer_account_id=prop.customer_account_id,
        idempotency_key=idempotency_key(prop),
        proposal_id=prop.id,
        review_id=review.id,
        run_id=prop.run_id,
        ticket_id=prop.ticket_id,
        action_kind=prop.action_kind,
        adapter="local",
        destination=prop.destination,
        payload_hash=prop.payload_hash,
        status="succeeded",
    )
    try:
        with db.begin_nested():
            db.add(record)
            db.flush()
    except IntegrityError:
        # The proposal row lock serializes executors, so this is a last line of defense.
        return db.execute(select(ActionRecord).where(ActionRecord.proposal_id == proposal_id)).scalar_one()

    receipt: dict[str, Any] = {"mode": "local", "note": "Recorded in RelayOps only. No email or external write."}
    msg = TicketMessage(
        ticket_id=ticket.id,
        organization_id=ticket.organization_id,
        customer_account_id=ticket.customer_account_id,
        author_user_id=review.reviewer_user_id,
        author_kind="staff",
        visibility="customer",
        body=prop.payload["customer_reply"],
        action_id=record.id,
        created_at=now,
    )
    db.add(msg)
    db.flush()
    receipt["customer_message_id"] = msg.id
    if ticket.first_responded_at is None:
        ticket.first_responded_at = now
    # Drafting or replying never resolves a ticket; it waits on the customer or engineering.
    ticket.status = "pending_customer"
    ticket.updated_at = now

    if prop.action_kind == ActionKind.CREATE_ENGINEERING_HANDOFF:
        h = prop.payload["handoff"]
        n = db.execute(
            select(func.count(EngineeringIssue.id)).where(EngineeringIssue.organization_id == prop.organization_id)
        ).scalar_one()
        issue = EngineeringIssue(
            organization_id=prop.organization_id,
            key=f"LOCAL-{n + 1}",
            title=h["title"][:300],
            kind="feature" if prop.route == "feature_request" else "bug",
            component=h["component"],
            status="open",
            affected_versions=[v for v in [prop.payload.get("computed_facts", {}).get("product_version")] if v],
            error_signature=prop.payload.get("computed_facts", {}).get("error_signature"),
            owner_team=h.get("team") or "unassigned",
            description=h.get("summary") or "",
            origin="local_handoff",
            origin_action_id=record.id,
        )
        db.add(issue)
        db.flush()
        db.add(
            TicketIssueLink(
                organization_id=prop.organization_id,
                ticket_id=ticket.id,
                issue_id=issue.id,
                link_kind="handoff",
                action_id=record.id,
            )
        )
        receipt |= {"engineering_issue_id": issue.id, "engineering_issue_key": issue.key, "owner": issue.owner_team}
    elif prop.action_kind == ActionKind.LINK_ENGINEERING_ISSUE:
        linked_issue = db.get(EngineeringIssue, prop.payload["issue_id"])
        assert linked_issue is not None and linked_issue.organization_id == prop.organization_id
        link = db.execute(
            select(TicketIssueLink).where(
                TicketIssueLink.ticket_id == ticket.id, TicketIssueLink.issue_id == linked_issue.id
            )
        ).scalar_one_or_none()
        if link is None:
            db.add(
                TicketIssueLink(
                    organization_id=prop.organization_id,
                    ticket_id=ticket.id,
                    issue_id=linked_issue.id,
                    link_kind=prop.payload.get("link_kind", "known_issue"),
                    action_id=record.id,
                )
            )
        receipt |= {
            "engineering_issue_id": linked_issue.id,
            "engineering_issue_key": linked_issue.key,
            "already_linked": link is not None,
        }
    elif prop.action_kind == ActionKind.LINK_INCIDENT:
        inc_id = prop.payload["incident_id"]
        inc_link = db.execute(
            select(IncidentTicketLink).where(
                IncidentTicketLink.incident_id == inc_id, IncidentTicketLink.ticket_id == ticket.id
            )
        ).scalar_one_or_none()
        if inc_link is None:
            db.add(
                IncidentTicketLink(
                    organization_id=prop.organization_id,
                    incident_id=inc_id,
                    ticket_id=ticket.id,
                    linked_by_user_id=review.reviewer_user_id,
                )
            )
        receipt |= {"incident_id": inc_id, "already_linked": inc_link is not None}
    elif prop.action_kind == ActionKind.ESCALATE_SPECIALIST:
        ticket.restricted = True
        db.add(
            TicketMessage(
                ticket_id=ticket.id,
                organization_id=ticket.organization_id,
                customer_account_id=ticket.customer_account_id,
                author_kind="system",
                visibility="internal",
                body="Escalated to restricted specialist review (local queue).",
                action_id=record.id,
                created_at=now,
            )
        )
        receipt["specialist_queue"] = "restricted-review (local)"

    record.receipt = receipt
    record.completed_at = utcnow()
    prop.status = "executed"
    art = db.execute(select(Artifact).where(Artifact.run_id == prop.run_id)).scalars().all()
    for a in art:
        a.review_status = "approved"
    db.add(
        OutboxMessage(
            organization_id=prop.organization_id,
            action_id=record.id,
            topic=f"local.{prop.action_kind}",
            payload={"ticket_id": ticket.id, "receipt": receipt},
        )
    )
    audit.record(
        db,
        organization_id=prop.organization_id,
        action="action.executed",
        target_type="action",
        target_id=record.id,
        actor_kind="system",
        detail={"proposal_id": prop.id, "kind": prop.action_kind, "receipt": receipt},
    )
    return record


def deliver_outbox(db: Session, limit: int = 20) -> int:
    """Local-mode delivery marks messages delivered; nothing leaves the application."""
    rows = list(
        db.execute(
            select(OutboxMessage)
            .where(OutboxMessage.status == "pending")
            .order_by(OutboxMessage.created_at)
            .with_for_update(skip_locked=True)
            .limit(limit)
        ).scalars()
    )
    for m in rows:
        m.attempts += 1
        m.status = "delivered"
        m.delivered_at = utcnow()
    return len(rows)


# --- Simulated external connector (disabled in the product; used for failure-semantics tests) ---------------


class RemoteTimeout(Exception):
    """The request may or may not have been applied remotely."""


class RemoteRejected(Exception):
    pass


class IssueConnector(Protocol):
    def create_issue(self, *, marker: str, title: str) -> str: ...

    def find_by_marker(self, marker: str) -> str | None: ...


@dataclass
class SimulatedIssueConnector:
    """Deterministic fake remote tracker. `mode` scripts the next create call's behavior."""

    mode: str = "success"  # success | reject | timeout_after_success | timeout_before_create | unreachable
    issues: dict[str, str] = field(default_factory=dict)
    create_calls: int = 0

    def create_issue(self, *, marker: str, title: str) -> str:
        self.create_calls += 1
        if self.mode == "reject":
            raise RemoteRejected("422 validation failed")
        if self.mode == "timeout_before_create":
            raise RemoteTimeout("timed out")
        remote_id = f"SIM-{len(self.issues) + 1}"
        self.issues[marker] = remote_id
        if self.mode == "timeout_after_success":
            raise RemoteTimeout("response lost after create")
        return remote_id

    def find_by_marker(self, marker: str) -> str | None:
        if self.mode == "unreachable":
            raise RemoteTimeout("search unavailable")
        return self.issues.get(marker)


def push_external(db: Session, record: ActionRecord, connector: IssueConnector, title: str) -> ActionRecord:
    """Mirror a local handoff to an external tracker; distinct states for success, rejection, and unknown."""
    if record.status in ("succeeded", "reconciled") and record.receipt.get("external_id"):
        return record
    if record.status == "unknown":
        return reconcile(db, record, connector)
    try:
        remote = connector.create_issue(marker=record.idempotency_key, title=title)
    except RemoteRejected as exc:
        record.status = "failed"
        record.receipt = {**record.receipt, "external_error": str(exc)}
    except RemoteTimeout as exc:
        record.status = "unknown"
        record.receipt = {**record.receipt, "external_error": str(exc), "needs_reconciliation": True}
    else:
        record.status = "succeeded"
        record.receipt = {**record.receipt, "external_id": remote}
    audit.record(
        db,
        organization_id=record.organization_id,
        action="action.external_push",
        target_type="action",
        target_id=record.id,
        actor_kind="system",
        outcome={"succeeded": "ok"}.get(record.status, record.status),
        detail={"adapter": "simulated", "status": record.status},
    )
    return record


def reconcile(db: Session, record: ActionRecord, connector: IssueConnector) -> ActionRecord:
    try:
        found = connector.find_by_marker(record.idempotency_key)
    except RemoteTimeout:
        return record  # still unknown; surfaced to operators, never recreated blindly
    if found:
        record.status = "reconciled"
        record.receipt = {**record.receipt, "external_id": found, "needs_reconciliation": False}
    else:
        record.receipt = {**record.receipt, "reconciliation": "marker not found; operator decision required"}
    audit.record(
        db,
        organization_id=record.organization_id,
        action="action.reconciled",
        target_type="action",
        target_id=record.id,
        actor_kind="system",
        outcome="ok" if found else "unknown",
        detail={"found": bool(found)},
    )
    return record
