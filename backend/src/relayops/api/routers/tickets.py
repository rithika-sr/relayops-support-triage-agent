from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from relayops.api import serializers as ser
from relayops.api.deps import DB, current_principal, staff_principal
from relayops.domain.scope import NotFound, Principal, ValidationFailed
from relayops.models import (
    ActionRecord,
    CustomerAccount,
    EngineeringIssue,
    Incident,
    IncidentTicketLink,
    InvestigationRun,
    Membership,
    Proposal,
    SavedView,
    TicketIssueLink,
    TicketMessage,
    User,
)
from relayops.repositories import scoped
from relayops.services import tickets as ticket_service

router = APIRouter(tags=["tickets"])


class TicketCreate(BaseModel):
    subject: str = Field(max_length=300)
    body: str = Field(max_length=10_000)
    reported_severity: str = "normal"
    component: str | None = None
    product_version: str | None = Field(default=None, max_length=32)
    error_code: str | None = Field(default=None, max_length=80)
    customer_account_id: str | None = None
    external_event_id: str | None = Field(default=None, max_length=120)


class MessageCreate(BaseModel):
    body: str = Field(max_length=10_000)
    visibility: str = "customer"


class TicketPatch(BaseModel):
    status: str | None = None
    priority: str | None = None
    component: str | None = None
    product_version: str | None = None
    error_code: str | None = None


def _accounts(db: Session, ids: set[str]) -> dict[str, CustomerAccount]:
    if not ids:
        return {}
    return {a.id: a for a in db.execute(select(CustomerAccount).where(CustomerAccount.id.in_(ids))).scalars()}


def _previews(db: Session, p: Principal, ids: list[str]) -> dict[str, str]:
    """Latest customer-visible message per ticket, trimmed, for list previews."""
    if not ids:
        return {}
    out: dict[str, str] = {}
    rows = db.execute(
        select(TicketMessage.ticket_id, TicketMessage.body)
        .where(
            TicketMessage.ticket_id.in_(ids),
            TicketMessage.organization_id == p.organization_id,
            TicketMessage.visibility == "customer",
        )
        .order_by(TicketMessage.created_at.desc())
    ).all()
    for tid, body in rows:
        out.setdefault(tid, body[:180])
    return out


def _user_names(db: Session, ids: set[str]) -> dict[str, str]:
    if not ids:
        return {}
    return {u.id: u.name for u in db.execute(select(User).where(User.id.in_(ids))).scalars()}


@router.get("/tickets")
def list_tickets(
    q: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    account_id: str | None = None,
    component: str | None = None,
    assignee: str | None = None,
    queue: str | None = None,
    sort: str = "newest",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    p: Principal = Depends(current_principal),
    db: Session = DB,
) -> dict[str, Any]:
    rows, total = ticket_service.list_tickets(
        db,
        p,
        q=q,
        status=status,
        priority=priority,
        account_id=account_id,
        component=component,
        assignee=assignee,
        queue=queue,
        sort=sort,
        page=page,
        page_size=page_size,
    )
    accts = _accounts(db, {t.customer_account_id for t in rows})
    previews = _previews(db, p, [t.id for t in rows])
    names = _user_names(db, {t.assignee_user_id for t in rows if t.assignee_user_id})
    return {
        "items": [
            {
                **ser.ticket(t, p, accts.get(t.customer_account_id)),
                "preview": previews.get(t.id),
                **(
                    {
                        "assignee": {"id": t.assignee_user_id, "name": names.get(t.assignee_user_id or "")}
                        if t.assignee_user_id
                        else None
                    }
                    if p.is_staff
                    else {}
                ),
            }
            for t in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/tickets/export.csv")
def export_tickets(
    status: str | None = None,
    account_id: str | None = None,
    p: Principal = Depends(staff_principal),
    db: Session = DB,
) -> Response:
    rows, _ = ticket_service.list_tickets(db, p, status=status, account_id=account_id, page_size=100)
    page = 2
    while True:
        more, _ = ticket_service.list_tickets(db, p, status=status, account_id=account_id, page=page, page_size=100)
        if not more:
            break
        rows += more
        page += 1
    accts = _accounts(db, {t.customer_account_id for t in rows})
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "number",
            "subject",
            "account",
            "status",
            "priority",
            "component",
            "product_version",
            "created_at",
            "first_response_due_at",
            "first_responded_at",
        ]
    )
    for t in rows:
        w.writerow(
            [
                t.number,
                t.subject,
                accts[t.customer_account_id].name,
                t.status,
                t.priority,
                t.component or "",
                t.product_version or "",
                ser.iso(t.created_at),
                ser.iso(t.first_response_due_at) or "",
                ser.iso(t.first_responded_at) or "",
            ]
        )
    return Response(
        buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="relayops-tickets.csv"'},
    )


@router.post("/tickets", status_code=201)
def create_ticket(body: TicketCreate, p: Principal = Depends(current_principal), db: Session = DB) -> dict[str, Any]:
    t, created = ticket_service.create_ticket(db, p, ticket_service.TicketInput(**body.model_dump()))
    return {"ticket": ser.ticket(t, p), "created": created}


@router.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: str, p: Principal = Depends(current_principal), db: Session = DB) -> dict[str, Any]:
    t = scoped.get_ticket(db, p, ticket_id)
    msgs = list(db.execute(scoped.messages(p, t.id)).scalars())
    authors = {
        u.id: u.name
        for u in db.execute(
            select(User).where(User.id.in_({m.author_user_id for m in msgs if m.author_user_id}))
        ).scalars()
    }
    out: dict[str, Any] = {
        "ticket": ser.ticket(t, p, db.get(CustomerAccount, t.customer_account_id)),
        "messages": [ser.message(m, authors.get(m.author_user_id or "")) for m in msgs],
    }
    if p.is_staff:
        out["account"] = ticket_service.account_context(db, p, t)
        runs = db.execute(
            scoped.runs(p).where(InvestigationRun.ticket_id == t.id).order_by(InvestigationRun.created_at.desc())
        ).scalars()
        out["runs"] = [
            {
                "id": r.id,
                "status": r.status,
                "mode": r.mode,
                "route": r.route,
                "playbook": r.playbook_key,
                "created_at": ser.iso(r.created_at),
            }
            for r in runs
        ]
        props = db.execute(
            scoped.proposals(p).where(Proposal.ticket_id == t.id).order_by(Proposal.created_at.desc())
        ).scalars()
        out["proposals"] = [
            {
                "id": x.id,
                "run_id": x.run_id,
                "version": x.version,
                "status": x.status,
                "route": x.route,
                "action_kind": x.action_kind,
                "ticket_revision": x.ticket_revision,
                "verification_status": x.verification_status,
                "created_at": ser.iso(x.created_at),
            }
            for x in props
        ]
        acts = db.execute(
            select(ActionRecord)
            .where(ActionRecord.organization_id == p.organization_id, ActionRecord.ticket_id == t.id)
            .order_by(ActionRecord.created_at)
        ).scalars()
        out["actions"] = [
            {
                "id": a.id,
                "kind": a.action_kind,
                "adapter": a.adapter,
                "status": a.status,
                "receipt": a.receipt,
                "created_at": ser.iso(a.created_at),
                "proposal_id": a.proposal_id,
            }
            for a in acts
        ]
        links = db.execute(
            select(TicketIssueLink, EngineeringIssue)
            .join(EngineeringIssue, EngineeringIssue.id == TicketIssueLink.issue_id)
            .where(TicketIssueLink.ticket_id == t.id, TicketIssueLink.organization_id == p.organization_id)
        ).all()
        out["issue_links"] = [
            {"issue_id": i.id, "key": i.key, "title": i.title, "status": i.status, "link_kind": link.link_kind}
            for link, i in links
        ]
    inc = db.execute(
        scoped.incidents(p)
        .join(IncidentTicketLink, IncidentTicketLink.incident_id == Incident.id)
        .where(IncidentTicketLink.ticket_id == t.id)
    ).scalars()
    out["incidents"] = [
        {
            "id": i.id,
            "title": i.title,
            "status": i.status,
            **(
                {"public_summary": i.public_summary}
                if not p.is_staff
                else {"severity": i.severity, "public_visible": i.public_visible}
            ),
        }
        for i in inc
    ]
    return out


@router.post("/tickets/{ticket_id}/messages", status_code=201)
def add_message(
    ticket_id: str, body: MessageCreate, p: Principal = Depends(current_principal), db: Session = DB
) -> dict[str, Any]:
    m = ticket_service.add_message(db, p, ticket_id, body=body.body, visibility=body.visibility)
    return ser.message(m, p.name)


@router.patch("/tickets/{ticket_id}")
def patch_ticket(
    ticket_id: str, body: TicketPatch, p: Principal = Depends(staff_principal), db: Session = DB
) -> dict[str, Any]:
    t = ticket_service.update_ticket(db, p, ticket_id, body.model_dump(exclude_unset=True))
    return ser.ticket(t, p)


class AssignBody(BaseModel):
    assignee_user_id: str | None = None


class BulkBody(BaseModel):
    ticket_ids: list[str] = Field(min_length=1, max_length=100)
    changes: dict[str, str | None]


class ViewBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    query: str = Field(max_length=500)


@router.post("/tickets/{ticket_id}/assign")
def assign(
    ticket_id: str, body: AssignBody, p: Principal = Depends(staff_principal), db: Session = DB
) -> dict[str, Any]:
    t = ticket_service.assign(db, p, ticket_id, body.assignee_user_id)
    return ser.ticket(t, p)


@router.post("/tickets/bulk")
def bulk(body: BulkBody, p: Principal = Depends(staff_principal), db: Session = DB) -> dict[str, Any]:
    return ticket_service.bulk_update(db, p, body.ticket_ids, body.changes)


@router.get("/home")
def home(p: Principal = Depends(staff_principal), db: Session = DB) -> dict[str, Any]:
    return ticket_service.home(db, p)


@router.get("/staff")
def staff_members(p: Principal = Depends(staff_principal), db: Session = DB) -> list[dict[str, str]]:
    rows = db.execute(
        select(User, Membership.role)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.organization_id == p.organization_id, Membership.role.in_(("admin", "support")))
        .order_by(User.name)
    ).all()
    return [{"id": u.id, "name": u.name, "role": role} for u, role in rows]


@router.get("/views")
def list_views(p: Principal = Depends(staff_principal), db: Session = DB) -> list[dict[str, str]]:
    rows = db.execute(
        select(SavedView)
        .where(SavedView.user_id == p.user_id, SavedView.organization_id == p.organization_id)
        .order_by(SavedView.name)
    ).scalars()
    return [{"id": v.id, "name": v.name, "query": v.query} for v in rows]


@router.post("/views", status_code=201)
def save_view(body: ViewBody, p: Principal = Depends(staff_principal), db: Session = DB) -> dict[str, str]:
    if body.query.startswith(("http", "/")) or "\n" in body.query:
        raise ValidationFailed("a view stores only the inbox query string")
    v = db.execute(
        select(SavedView).where(
            SavedView.user_id == p.user_id,
            SavedView.organization_id == p.organization_id,
            SavedView.name == body.name.strip(),
        )
    ).scalar_one_or_none()
    if v is None:
        v = SavedView(organization_id=p.organization_id, user_id=p.user_id, name=body.name.strip(), query="")
        db.add(v)
    v.query = body.query.lstrip("?")
    db.flush()
    return {"id": v.id, "name": v.name, "query": v.query}


@router.delete("/views/{view_id}", status_code=204)
def delete_view(view_id: str, p: Principal = Depends(staff_principal), db: Session = DB) -> None:
    v = db.execute(
        select(SavedView).where(SavedView.id == view_id, SavedView.user_id == p.user_id)
    ).scalar_one_or_none()
    if v is None:
        raise NotFound("view not found")
    db.delete(v)


@router.get("/accounts")
def list_accounts(p: Principal = Depends(current_principal), db: Session = DB) -> list[dict[str, Any]]:
    return [
        {"id": a.id, "name": a.name, "plan": a.plan, "product_version": a.product_version}
        for a in db.execute(scoped.accounts(p).order_by(CustomerAccount.name)).scalars()
    ]


@router.get("/overview")
def overview(p: Principal = Depends(staff_principal), db: Session = DB) -> dict[str, Any]:
    return ticket_service.overview(db, p)
