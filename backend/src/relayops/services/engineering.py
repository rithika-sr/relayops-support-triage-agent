"""Engineering issues: board, search, duplicate candidates, ownership, and linked tickets."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import Session

from relayops.domain.incidents import normalize_signature
from relayops.domain.scope import Principal
from relayops.models import ComponentOwner, EngineeringIssue, Ticket, TicketIssueLink
from relayops.repositories import scoped


def issue_dict(i: EngineeringIssue, *, linked: int | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": i.id,
        "key": i.key,
        "title": i.title,
        "kind": i.kind,
        "component": i.component,
        "status": i.status,
        "affected_versions": i.affected_versions,
        "fixed_in_version": i.fixed_in_version,
        "error_signature": i.error_signature,
        "owner_team": i.owner_team,
        "description": i.description,
        "origin": i.origin,
        "origin_action_id": i.origin_action_id,
        "updated_at": i.updated_at.isoformat(),
    }
    if linked is not None:
        out["linked_tickets"] = linked
    return out


def search_issues(
    db: Session,
    organization_id: str,
    *,
    query: str,
    component: str | None,
    product_version: str | None,
    error_signature: str | None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Organization-scoped issue search with explicit signature/version match annotations."""
    stmt = select(EngineeringIssue).where(EngineeringIssue.organization_id == organization_id)
    words = [w for w in re.findall(r"[a-z0-9_]+", query.lower()) if len(w) > 2][:8]
    conds: list[ColumnElement[bool]] = [EngineeringIssue.title.ilike(f"%{w}%") for w in words]
    sig = normalize_signature(error_signature)
    if sig:
        conds.append(EngineeringIssue.error_signature == sig)
    if component:
        conds.append(EngineeringIssue.component == component)
    if conds:
        stmt = stmt.where(or_(*conds))
    rows = list(db.execute(stmt).scalars())

    def score(i: EngineeringIssue) -> tuple[int, str]:
        s = 0
        s += 4 if sig and i.error_signature == sig else 0
        s += 2 if component and i.component == component else 0
        s += 3 if product_version and product_version in (i.affected_versions or []) else 0
        s += sum(1 for w in words if w in i.title.lower())
        return (-s, i.key)

    rows.sort(key=score)
    out = []
    for i in rows[:limit]:
        d = issue_dict(i)
        d["match"] = {
            "signature": bool(sig and i.error_signature == sig),
            "component": bool(component and i.component == component),
            "version": bool(product_version and product_version in (i.affected_versions or [])),
        }
        out.append(d)
    return out


def owner_for(db: Session, organization_id: str, component: str | None) -> dict[str, str]:
    if component:
        row = db.execute(
            select(ComponentOwner).where(
                ComponentOwner.organization_id == organization_id, ComponentOwner.component == component
            )
        ).scalar_one_or_none()
        if row:
            return {"component": row.component, "team": row.team, "escalation": row.escalation}
    return {"component": component or "unassigned", "team": "support-triage", "escalation": "support lead (local)"}


def board(db: Session, p: Principal, *, component: str | None = None, kind: str | None = None) -> dict[str, Any]:
    scoped.require_staff(p)
    stmt = scoped.issues(p)
    if component:
        stmt = stmt.where(EngineeringIssue.component == component)
    if kind:
        stmt = stmt.where(EngineeringIssue.kind == kind)
    issues = list(db.execute(stmt.order_by(EngineeringIssue.key)).scalars())
    counts = dict(
        db.execute(
            select(TicketIssueLink.issue_id, func.count(TicketIssueLink.id))
            .where(TicketIssueLink.organization_id == p.organization_id)
            .group_by(TicketIssueLink.issue_id)
        ).all()  # type: ignore[arg-type]
    )
    columns: dict[str, list[dict[str, Any]]] = {"open": [], "investigating": [], "fixed": [], "wont_fix": []}
    for i in issues:
        columns.setdefault(i.status, []).append(issue_dict(i, linked=int(counts.get(i.id, 0))))
    # Duplicate candidates: issues sharing a component and normalized signature.
    sigs: dict[tuple[str, str], list[str]] = {}
    for i in issues:
        if i.error_signature:
            sigs.setdefault((i.component, i.error_signature), []).append(i.key)
    dupes = [
        {"component": c, "signature": s, "issues": keys, "note": "same signature; compare affected versions"}
        for (c, s), keys in sigs.items()
        if len(keys) > 1
    ]
    owners = [
        {"component": o.component, "team": o.team, "escalation": o.escalation}
        for o in db.execute(
            select(ComponentOwner)
            .where(ComponentOwner.organization_id == p.organization_id)
            .order_by(ComponentOwner.component)
        ).scalars()
    ]
    return {"columns": columns, "duplicate_candidates": dupes, "owners": owners}


def issue_detail(db: Session, p: Principal, issue_id: str) -> dict[str, Any]:
    scoped.require_staff(p)
    issue = scoped.one(db, scoped.issues(p).where(EngineeringIssue.id == issue_id), "issue")
    rows = db.execute(
        select(TicketIssueLink, Ticket)
        .join(Ticket, Ticket.id == TicketIssueLink.ticket_id)
        .where(TicketIssueLink.issue_id == issue.id, TicketIssueLink.organization_id == p.organization_id)
        .order_by(Ticket.created_at.desc())
    ).all()
    return {
        "issue": issue_dict(issue),
        "tickets": [
            {
                "id": t.id,
                "number": t.number,
                "subject": t.subject,
                "status": t.status,
                "customer_account_id": t.customer_account_id,
                "product_version": t.product_version,
                "link_kind": link.link_kind,
                "action_id": link.action_id,
                "historical": t.is_historical,
            }
            for link, t in rows
        ],
        "distinct_accounts": len({t.customer_account_id for _, t in rows}),
    }
