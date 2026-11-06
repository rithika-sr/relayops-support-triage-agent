"""Ticket intake, messages, staff updates, listing, and overview counts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.orm import Session

from relayops.core.clock import utcnow
from relayops.domain.policies import COMPONENTS, PRIORITIES, decide_target, entitlements_for, target_state
from relayops.domain.scope import AccessDenied, Principal, ValidationFailed
from relayops.models import CustomerAccount, InvestigationRun, Organization, Proposal, Ticket, TicketMessage
from relayops.repositories import scoped
from relayops.services import audit

STATUSES = ("open", "pending_review", "pending_customer", "resolved", "closed")
SEVERITIES = ("low", "normal", "high", "critical")


@dataclass(frozen=True)
class TicketInput:
    subject: str
    body: str
    reported_severity: str = "normal"
    component: str | None = None
    product_version: str | None = None
    error_code: str | None = None
    customer_account_id: str | None = None
    external_event_id: str | None = None
    # Server-set provenance. API request models do not expose these fields.
    source_kind: str | None = None
    source_system: str | None = None
    source_connection_id: str | None = None
    import_batch_id: str | None = None
    source_event_at: datetime | None = None


def _clean(inp: TicketInput) -> TicketInput:
    subject, body = inp.subject.strip(), inp.body.strip()
    if not (3 <= len(subject) <= 300):
        raise ValidationFailed("subject must be 3-300 characters")
    if not (5 <= len(body) <= 10_000):
        raise ValidationFailed("description must be 5-10,000 characters")
    if inp.reported_severity not in SEVERITIES:
        raise ValidationFailed("unknown severity")
    if inp.component and inp.component not in COMPONENTS:
        raise ValidationFailed("unknown component")
    return TicketInput(
        subject=subject,
        body=body,
        reported_severity=inp.reported_severity,
        component=inp.component or None,
        product_version=(inp.product_version or "").strip()[:32] or None,
        error_code=(inp.error_code or "").strip()[:80] or None,
        customer_account_id=inp.customer_account_id,
        external_event_id=(inp.external_event_id or "").strip()[:120] or None,
        source_kind=inp.source_kind,
        source_system=inp.source_system,
        source_connection_id=inp.source_connection_id,
        import_batch_id=inp.import_batch_id,
        source_event_at=inp.source_event_at,
    )


def create_ticket(db: Session, p: Principal, raw: TicketInput) -> tuple[Ticket, bool]:
    """Returns (ticket, created). Replayed intake with the same external event ID returns the original."""
    inp = _clean(raw)
    if p.is_staff:
        if not inp.customer_account_id:
            raise ValidationFailed("choose the customer account for this ticket")
        account = scoped.get_account(db, p, inp.customer_account_id)
    else:
        # Customers always file against their own account, whatever the request body says.
        account = scoped.get_account(db, p, p.customer_account_id or "")

    if inp.external_event_id:
        existing = db.execute(
            select(Ticket).where(
                Ticket.organization_id == p.organization_id, Ticket.external_event_id == inp.external_event_id
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.customer_account_id != account.id:
                raise AccessDenied("external event belongs to a different account")
            return existing, False

    now = utcnow()
    decision = decide_target(
        plan=account.plan, reported_severity=inp.reported_severity, subject=inp.subject, body=inp.body, created_at=now
    )
    number = (
        db.execute(
            select(func.coalesce(func.max(Ticket.number), 1000)).where(Ticket.organization_id == p.organization_id)
        ).scalar_one()
        + 1
    )
    org = db.get(Organization, p.organization_id)
    data_class = org.data_class if org else "unknown"
    source_kind = inp.source_kind or ("manual" if p.is_staff else "portal")
    ticket = Ticket(
        data_class=data_class,
        source_kind=source_kind,
        source_system=inp.source_system,
        source_connection_id=inp.source_connection_id,
        import_batch_id=inp.import_batch_id,
        source_event_at=inp.source_event_at,
        received_at=now,
        organization_id=p.organization_id,
        customer_account_id=account.id,
        number=number,
        subject=inp.subject,
        reported_severity=inp.reported_severity,
        priority=decision.priority,
        component=inp.component,
        product_version=inp.product_version or account.product_version,
        error_code=inp.error_code,
        restricted=decision.restricted,
        external_event_id=inp.external_event_id,
        created_by_user_id=p.user_id,
        created_at=now,
        updated_at=now,
        first_response_due_at=decision.due_at,
        target_policy=decision.as_policy(),
    )
    db.add(ticket)
    db.flush()
    db.add(
        TicketMessage(
            data_class=data_class,
            source_kind=source_kind,
            ticket_id=ticket.id,
            organization_id=p.organization_id,
            customer_account_id=account.id,
            author_user_id=p.user_id,
            author_kind="staff" if p.is_staff else "customer",
            visibility="customer",
            body=inp.body,
            created_at=now,
        )
    )
    audit.record(
        db,
        organization_id=p.organization_id,
        actor=p,
        action="ticket.created",
        target_type="ticket",
        target_id=ticket.id,
        detail={"number": number, "priority": decision.priority},
    )
    return ticket, True


def add_message(db: Session, p: Principal, ticket_id: str, *, body: str, visibility: str) -> TicketMessage:
    ticket = scoped.get_ticket(db, p, ticket_id, for_update=True)
    body = body.strip()
    if not (1 <= len(body) <= 10_000):
        raise ValidationFailed("message must be 1-10,000 characters")
    if not p.is_staff:
        visibility = "customer"
    if visibility not in ("customer", "internal"):
        raise ValidationFailed("unknown visibility")
    if p.is_staff and visibility == "customer":
        raise ValidationFailed("staff replies to customers go through a reviewed proposal")
    now = utcnow()
    msg = TicketMessage(
        data_class=ticket.data_class,
        source_kind="portal" if not p.is_staff else "manual",
        ticket_id=ticket.id,
        organization_id=ticket.organization_id,
        customer_account_id=ticket.customer_account_id,
        author_user_id=p.user_id,
        author_kind="staff" if p.is_staff else "customer",
        visibility=visibility,
        body=body,
        created_at=now,
    )
    db.add(msg)
    if not p.is_staff:
        # New customer facts change what was reviewed: bump the revision so older approvals go stale.
        ticket.revision += 1
        if ticket.status in ("pending_customer", "resolved"):
            ticket.status = "open"
    ticket.updated_at = now
    db.flush()
    audit.record(
        db,
        organization_id=ticket.organization_id,
        actor=p,
        action="ticket.message_added",
        target_type="ticket",
        target_id=ticket.id,
        detail={"visibility": visibility, "revision": ticket.revision},
    )
    return msg


def update_ticket(db: Session, p: Principal, ticket_id: str, changes: dict[str, Any]) -> Ticket:
    scoped.require_staff(p)
    ticket = scoped.get_ticket(db, p, ticket_id, for_update=True)
    allowed = {"status", "priority", "component", "product_version", "error_code"}
    unknown = set(changes) - allowed
    if unknown:
        raise ValidationFailed(f"cannot change {', '.join(sorted(unknown))}")
    if "status" in changes and changes["status"] not in STATUSES:
        raise ValidationFailed("unknown status")
    if "priority" in changes and changes["priority"] not in PRIORITIES:
        raise ValidationFailed("unknown priority")
    if changes.get("component") and changes["component"] not in COMPONENTS:
        raise ValidationFailed("unknown component")
    before = {k: getattr(ticket, k) for k in changes}
    material = False
    for k, v in changes.items():
        if getattr(ticket, k) != v:
            setattr(ticket, k, v if k in ("status", "priority") else (v or None))
            material = material or k in {"component", "product_version", "error_code"}
    if changes.get("status") == "resolved":
        ticket.resolved_at = utcnow()
    if material:
        ticket.revision += 1
    ticket.updated_at = utcnow()
    audit.record(
        db,
        organization_id=ticket.organization_id,
        actor=p,
        action="ticket.updated",
        target_type="ticket",
        target_id=ticket.id,
        detail={"before": before, "after": changes, "revision": ticket.revision},
    )
    return ticket


def list_tickets(
    db: Session,
    p: Principal,
    *,
    q: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    account_id: str | None = None,
    component: str | None = None,
    include_historical: bool = False,
    page: int = 1,
    page_size: int = 25,
) -> tuple[list[Ticket], int]:
    stmt = scoped.tickets(p)
    if not include_historical:
        stmt = stmt.where(Ticket.is_historical.is_(False))
    if q:
        like = f"%{q.strip()[:100]}%"
        conds: list[ColumnElement[bool]] = [Ticket.subject.ilike(like), Ticket.error_code.ilike(like)]
        if q.strip().lstrip("#").isdigit():
            conds.append(Ticket.number == int(q.strip().lstrip("#")))
        stmt = stmt.where(or_(*conds))
    if status:
        stmt = stmt.where(Ticket.status == status)
    if priority:
        stmt = stmt.where(Ticket.priority == priority)
    if account_id:
        stmt = stmt.where(Ticket.customer_account_id == account_id)
    if component:
        stmt = stmt.where(Ticket.component == component)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    page_size = max(1, min(page_size, 100))
    rows = db.execute(
        stmt.order_by(Ticket.created_at.desc(), Ticket.id).limit(page_size).offset((max(page, 1) - 1) * page_size)
    ).scalars()
    return list(rows), int(total)


def account_context(db: Session, p: Principal, ticket: Ticket) -> dict[str, Any]:
    account = db.get(CustomerAccount, ticket.customer_account_id)
    assert account is not None and account.organization_id == p.organization_id
    return {
        "id": account.id,
        "name": account.name,
        "plan": account.plan,
        "product_version": account.product_version,
        "region": account.region,
        "entitlements": entitlements_for(account.plan),
    }


def ticket_target(ticket: Ticket) -> dict[str, Any]:
    state = target_state(ticket.first_response_due_at, ticket.first_responded_at, utcnow())
    return {
        "due_at": ticket.first_response_due_at.isoformat() if ticket.first_response_due_at else None,
        "responded_at": ticket.first_responded_at.isoformat() if ticket.first_responded_at else None,
        **state,
        "policy": ticket.target_policy,
    }


def overview(db: Session, p: Principal) -> dict[str, Any]:
    scoped.require_staff(p)
    org = p.organization_id
    now = utcnow()
    live = and_(Ticket.organization_id == org, Ticket.is_historical.is_(False))

    def count(*conds: Any) -> int:
        return int(db.execute(select(func.count(Ticket.id)).where(live, *conds)).scalar_one())

    by_status = dict(
        db.execute(select(Ticket.status, func.count(Ticket.id)).where(live).group_by(Ticket.status)).all()  # type: ignore[arg-type]
    )
    by_component = dict(
        db.execute(
            select(func.coalesce(Ticket.component, "unassigned"), func.count(Ticket.id))
            .where(live, Ticket.status.in_(("open", "pending_review")))
            .group_by(Ticket.component)
        ).all()  # type: ignore[arg-type]
    )
    daily = db.execute(
        select(func.date_trunc("day", Ticket.created_at).label("d"), func.count(Ticket.id))
        .where(live, Ticket.created_at >= now - timedelta(days=14))
        .group_by("d")
        .order_by("d")
    ).all()
    pending_review = int(
        db.execute(
            select(func.count(Proposal.id)).where(Proposal.organization_id == org, Proposal.status == "pending_review")
        ).scalar_one()
    )
    runs_by_status = dict(
        db.execute(
            select(InvestigationRun.status, func.count(InvestigationRun.id))
            .where(InvestigationRun.organization_id == org)
            .group_by(InvestigationRun.status)
        ).all()  # type: ignore[arg-type]
    )
    return {
        "as_of": now.isoformat(),
        "open_tickets": count(Ticket.status.in_(("open", "pending_review"))),
        "breached_targets": count(
            Ticket.first_responded_at.is_(None),
            Ticket.first_response_due_at < now,
            Ticket.status.in_(("open", "pending_review")),
        ),
        "due_within_4h": count(
            Ticket.first_responded_at.is_(None),
            Ticket.first_response_due_at >= now,
            Ticket.first_response_due_at < now + timedelta(hours=4),
        ),
        "restricted_open": count(Ticket.restricted.is_(True), Ticket.status.in_(("open", "pending_review"))),
        "pending_review_proposals": pending_review,
        "tickets_by_status": by_status,
        "open_by_component": by_component,
        "created_per_day": [{"day": d.date().isoformat(), "count": c} for d, c in daily],
        "runs_by_status": runs_by_status,
    }
