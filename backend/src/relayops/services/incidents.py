"""Incident constellations (candidates), reviewed incidents, timelines, and public visibility."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from relayops.core.clock import utcnow
from relayops.domain.incidents import SignalTicket, group_signals
from relayops.domain.scope import Conflict, Principal, ValidationFailed
from relayops.models import (
    CustomerAccount,
    Deployment,
    ErrorAggregate,
    Incident,
    IncidentTicketLink,
    Organization,
    Ticket,
)
from relayops.repositories import scoped
from relayops.services import artifacts, audit

LOOKBACK = timedelta(days=14)


def incident_dict(
    i: Incident, *, staff: bool, linked: int | None = None, accounts: int | None = None
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": i.id,
        "title": i.title,
        "component": i.component,
        "status": i.status,
        "started_at": i.started_at.isoformat(),
        "resolved_at": i.resolved_at.isoformat() if i.resolved_at else None,
        "public_summary": i.public_summary if (i.public_visible or staff) else None,
    }
    if staff:
        out |= {
            "severity": i.severity,
            "error_signature": i.error_signature,
            "affected_versions": i.affected_versions,
            "internal_notes": i.internal_notes,
            "public_visible": i.public_visible,
            "linked_tickets": linked,
            "affected_accounts": accounts,
        }
    return out


def _signals(db: Session, organization_id: str) -> tuple[list[SignalTicket], dict[str, Ticket]]:
    since = utcnow() - LOOKBACK
    rows = list(
        db.execute(
            select(Ticket).where(
                Ticket.organization_id == organization_id,
                Ticket.is_historical.is_(False),
                Ticket.created_at >= since,
                Ticket.status.in_(("open", "pending_review", "pending_customer")),
            )
        ).scalars()
    )
    return (
        [
            SignalTicket(t.id, t.customer_account_id, t.component, t.error_code, t.product_version, t.created_at)
            for t in rows
        ],
        {t.id: t for t in rows},
    )


def candidates(db: Session, p: Principal, *, window_hours: int = 6) -> list[dict[str, Any]]:
    scoped.require_staff(p)
    if not 1 <= window_hours <= 72:
        raise ValidationFailed("window must be 1-72 hours")
    signals, by_id = _signals(db, p.organization_id)
    groups = group_signals(signals, window=timedelta(hours=window_hours))
    linked = {
        tid: iid
        for tid, iid in db.execute(
            select(IncidentTicketLink.ticket_id, IncidentTicketLink.incident_id).where(
                IncidentTicketLink.organization_id == p.organization_id
            )
        ).all()
    }
    names = dict(
        db.execute(
            select(CustomerAccount.id, CustomerAccount.name).where(CustomerAccount.organization_id == p.organization_id)
        ).all()
    )  # type: ignore[arg-type]
    incidents = list(db.execute(scoped.incidents(p).where(Incident.resolved_at.is_(None))).scalars())
    out = []
    for g in groups:
        existing = sorted({linked[t] for t in g.ticket_ids if t in linked})
        suggested = [i.id for i in incidents if i.component == g.component and i.error_signature == g.signature]
        out.append(
            {
                "key": g.key,
                "component": g.component,
                "signature": g.signature,
                "product_version": g.product_version,
                "ticket_count": len(g.ticket_ids),
                "distinct_accounts": g.distinct_accounts,
                "accounts": sorted(names.get(a, a) for a in g.account_ids),
                "first_reported_at": g.first_reported_at.isoformat() if g.first_reported_at else None,
                "last_reported_at": g.last_reported_at.isoformat() if g.last_reported_at else None,
                "tickets": [
                    {
                        "id": t,
                        "number": by_id[t].number,
                        "subject": by_id[t].subject,
                        "account": names.get(by_id[t].customer_account_id),
                        "created_at": by_id[t].created_at.isoformat(),
                        "incident_id": linked.get(t),
                    }
                    for t in g.ticket_ids
                ],
                "linked_incidents": existing,
                "suggested_incidents": suggested,
                "status": "candidate",
                "method": f"deterministic: component+signature+version, {window_hours}h window",
            }
        )
    return out


def _find_candidate(db: Session, p: Principal, key: str, window_hours: int) -> dict[str, Any]:
    for c in candidates(db, p, window_hours=window_hours):
        if c["key"] == key:
            return c
    raise Conflict("candidate changed or no longer exists; reload the board")


def confirm_candidate(
    db: Session,
    p: Principal,
    key: str,
    *,
    title: str,
    severity: str,
    window_hours: int = 6,
    incident_id: str | None = None,
    expected_ticket_ids: list[str] | None = None,
) -> Incident:
    """Human review step: create a reviewed incident from a candidate, or link it to an existing incident."""
    scoped.require_staff(p)
    cand = _find_candidate(db, p, key, window_hours)
    ids = [t["id"] for t in cand["tickets"]]
    if expected_ticket_ids is not None and sorted(expected_ticket_ids) != ids:
        raise Conflict("candidate membership changed since you reviewed it")
    if incident_id:
        inc = scoped.get_incident(db, p, incident_id)
    else:
        if severity not in ("P1", "P2", "P3", "P4"):
            raise ValidationFailed("severity must be P1-P4")
        if not title.strip():
            raise ValidationFailed("title is required")
        inc = Incident(
            organization_id=p.organization_id,
            title=title.strip()[:300],
            component=cand["component"],
            status="investigating",
            severity=severity,
            started_at=min(t.created_at for t in db.execute(select(Ticket).where(Ticket.id.in_(ids))).scalars()),
            error_signature=cand["signature"],
            affected_versions=[cand["product_version"]],
            public_visible=False,
            confirmed_by_user_id=p.user_id,
        )
        db.add(inc)
        db.flush()
    added = 0
    for tid in ids:
        exists = db.execute(
            select(IncidentTicketLink).where(
                IncidentTicketLink.incident_id == inc.id, IncidentTicketLink.ticket_id == tid
            )
        ).scalar_one_or_none()
        if exists is None:
            db.add(
                IncidentTicketLink(
                    organization_id=p.organization_id,
                    incident_id=inc.id,
                    ticket_id=tid,
                    linked_by_user_id=p.user_id,
                    candidate_key=key,
                )
            )
            added += 1
    audit.record(
        db,
        organization_id=p.organization_id,
        actor=p,
        action="incident.candidate_confirmed",
        target_type="incident",
        target_id=inc.id,
        detail={"candidate": key, "tickets": ids, "added": added, "distinct_accounts": cand["distinct_accounts"]},
    )
    return inc


def list_incidents(db: Session, p: Principal) -> list[dict[str, Any]]:
    rows = list(db.execute(scoped.incidents(p).order_by(Incident.started_at.desc())).scalars())
    if not p.is_staff:
        return [incident_dict(i, staff=False) for i in rows]
    out = []
    for i in rows:
        n, accts = db.execute(
            select(func.count(IncidentTicketLink.id), func.count(func.distinct(Ticket.customer_account_id)))
            .join(Ticket, Ticket.id == IncidentTicketLink.ticket_id)
            .where(IncidentTicketLink.incident_id == i.id)
        ).one()
        out.append(incident_dict(i, staff=True, linked=int(n), accounts=int(accts)))
    return out


def detail(db: Session, p: Principal, incident_id: str) -> dict[str, Any]:
    inc = scoped.get_incident(db, p, incident_id)
    if not p.is_staff:
        return {"incident": incident_dict(inc, staff=False)}
    rows = db.execute(
        select(IncidentTicketLink, Ticket, CustomerAccount)
        .join(Ticket, Ticket.id == IncidentTicketLink.ticket_id)
        .join(CustomerAccount, CustomerAccount.id == Ticket.customer_account_id)
        .where(IncidentTicketLink.incident_id == inc.id)
        .order_by(Ticket.created_at)
    ).all()
    tickets = [
        {
            "id": t.id,
            "number": t.number,
            "subject": t.subject,
            "account": a.name,
            "created_at": t.created_at.isoformat(),
            "status": t.status,
        }
        for _, t, a in rows
    ]
    return {
        "incident": incident_dict(
            inc, staff=True, linked=len(tickets), accounts=len({t.customer_account_id for _, t, _ in rows})
        ),
        "tickets": tickets,
        "timeline": timeline(db, p, inc),
    }


def timeline(db: Session, p: Principal, inc: Incident) -> list[dict[str, Any]]:
    """Shared timestamped timeline: customer reports, trusted records, and signals, each labeled by source."""
    start = inc.started_at - timedelta(hours=96)
    end = inc.resolved_at or utcnow()
    items: list[dict[str, Any]] = [
        {
            "at": inc.started_at.isoformat(),
            "lane": "trusted_record",
            "kind": "incident_start",
            "label": f"Incident start recorded ({inc.severity})",
            "source": f"incident:{inc.id}",
        },
    ]
    if inc.resolved_at:
        items.append(
            {
                "at": inc.resolved_at.isoformat(),
                "lane": "trusted_record",
                "kind": "incident_resolved",
                "label": "Incident resolved",
                "source": f"incident:{inc.id}",
            }
        )
    for d in db.execute(
        select(Deployment).where(
            Deployment.organization_id == p.organization_id,
            Deployment.component == inc.component,
            Deployment.deployed_at.between(start, end),
        )
    ).scalars():
        items.append(
            {
                "at": d.deployed_at.isoformat(),
                "lane": "trusted_record",
                "kind": "deployment",
                "label": f"{d.component} {d.version} deployed: {d.summary}",
                "source": f"deployment:{d.id}",
                "note": "temporal correlation only; not a confirmed cause",
            }
        )
    if inc.error_signature:
        first = db.execute(
            select(func.min(ErrorAggregate.bucket_start), func.sum(ErrorAggregate.count)).where(
                ErrorAggregate.organization_id == p.organization_id,
                ErrorAggregate.error_signature == inc.error_signature,
                ErrorAggregate.bucket_start.between(start, end),
            )
        ).one()
        if first[0]:
            items.append(
                {
                    "at": first[0].isoformat(),
                    "lane": "signal",
                    "kind": "errors_first_seen",
                    "label": f"{inc.error_signature} first seen in aggregates ({int(first[1])} errors in window)",
                    "source": f"error_aggregates:{inc.error_signature}",
                }
            )
    for _, t in db.execute(
        select(IncidentTicketLink, Ticket)
        .join(Ticket, Ticket.id == IncidentTicketLink.ticket_id)
        .where(IncidentTicketLink.incident_id == inc.id)
    ).all():
        items.append(
            {
                "at": t.created_at.isoformat(),
                "lane": "customer_report",
                "kind": "ticket",
                "label": f"#{t.number} reported: {t.subject}",
                "source": f"ticket:{t.id}",
            }
        )
    items.sort(key=lambda x: x["at"])
    return items


def update_incident(db: Session, p: Principal, incident_id: str, changes: dict[str, Any]) -> Incident:
    scoped.require_staff(p)
    inc = scoped.get_incident(db, p, incident_id)
    allowed = {"status", "public_summary", "public_visible", "internal_notes"}
    if set(changes) - allowed:
        raise ValidationFailed("unsupported change")
    if changes.get("public_visible") and not p.is_admin:
        raise scoped.AccessDenied("only an admin can publish an incident to customers")
    if changes.get("public_visible") and not (changes.get("public_summary") or inc.public_summary):
        raise ValidationFailed("write an approved public summary before publishing")
    if "status" in changes and changes["status"] not in ("investigating", "monitoring", "resolved"):
        raise ValidationFailed("unknown status")
    before = {k: getattr(inc, k) for k in changes}
    for k, v in changes.items():
        setattr(inc, k, v)
    if changes.get("status") == "resolved" and inc.resolved_at is None:
        inc.resolved_at = utcnow()
    audit.record(
        db,
        organization_id=p.organization_id,
        actor=p,
        action="incident.updated",
        target_type="incident",
        target_id=inc.id,
        detail={"before": before, "after": changes},
    )
    return inc


def draft_summary(db: Session, p: Principal, incident_id: str) -> Any:
    """Deterministic incident-summary artifact built from records; editable and re-verifiable."""
    d = detail(db, p, incident_id)
    inc = d["incident"]
    from relayops.models import Artifact

    lines = [
        f"# Incident summary: {inc['title']}",
        "",
        f"Status: {inc['status']}  ",
        f"Severity: {inc['severity']}  ",
        f"Component: {inc['component']}  ",
        f"Started: {inc['started_at']}",
        "",
        f"Linked tickets: {inc['linked_tickets']}  ",
        f"Affected accounts: {inc['affected_accounts']}",
        "",
        "## Timeline",
        "",
    ]
    lines += [f"- {x['at']} [{x['lane']}] {x['label']}" for x in d["timeline"]]
    lines += [
        "",
        "## Public summary",
        "",
        inc["public_summary"] or "_Not yet written._",
        "",
        "Deployment timing is listed as correlation only; no root cause is confirmed here.",
    ]
    org = db.get(Organization, p.organization_id)
    art = Artifact(
        data_class=org.data_class if org else "unknown",
        organization_id=p.organization_id,
        incident_id=incident_id,
        kind="incident_summary",
        title=f"Incident summary: {inc['title']}"[:300],
    )
    db.add(art)
    db.flush()
    v = artifacts.add_version(
        db,
        art,
        content="\n".join(lines),
        sources=[{"type": "incident", "id": incident_id}],
        verification=None,
        created_by=p.user_id,
        note="generated from records",
    )
    audit.record(
        db,
        organization_id=p.organization_id,
        actor=p,
        action="artifact.created",
        target_type="artifact",
        target_id=art.id,
        detail={"kind": "incident_summary"},
    )
    return art, v
