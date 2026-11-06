from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from relayops.api.deps import DB, staff_principal
from relayops.api.serializers import iso
from relayops.core.db import new_session
from relayops.domain.playbooks import GRAPH_NODES
from relayops.domain.scope import Principal
from relayops.models import ActionRecord, InvestigationRun, Proposal, Review, RunEvent, Ticket, User
from relayops.repositories import scoped
from relayops.services import review as review_service
from relayops.services import runs as run_service

router = APIRouter(tags=["investigations"])


class StartBody(BaseModel):
    playbook_key: str | None = None
    retrieval_mode: str | None = None


class EditBody(BaseModel):
    customer_reply: str = Field(max_length=3000)
    expected_version: int
    note: str | None = Field(default=None, max_length=500)


class ApproveBody(BaseModel):
    expected_version: int
    expected_payload_hash: str = Field(min_length=64, max_length=64)
    note: str | None = Field(default=None, max_length=500)


class RejectBody(BaseModel):
    expected_version: int
    note: str | None = Field(default=None, max_length=500)


def run_summary(r: InvestigationRun, ticket: Ticket | None = None) -> dict[str, Any]:
    return {
        "id": r.id,
        "ticket_id": r.ticket_id,
        "ticket_number": ticket.number if ticket else None,
        "ticket_subject": ticket.subject if ticket else None,
        "status": r.status,
        "mode": r.mode,
        "replay_of_run_id": r.replay_of_run_id,
        "compare_of_run_id": r.compare_of_run_id,
        "playbook": r.playbook_key,
        "playbook_revision": r.playbook_revision,
        "route": r.route,
        "verdict": r.verdict,
        "model_provider": r.model_provider,
        "model_name": r.model_name,
        "current_node": r.current_node,
        "usage": r.usage,
        "created_at": iso(r.created_at),
        "started_at": iso(r.started_at),
        "finished_at": iso(r.finished_at),
        "error": r.error,
    }


def event_dict(e: RunEvent) -> dict[str, Any]:
    return {"seq": e.seq, "kind": e.kind, "node": e.node, "payload": e.payload, "created_at": iso(e.created_at)}


def proposal_dict(db: Session, p: Proposal) -> dict[str, Any]:
    reviews = db.execute(
        select(Review, User)
        .join(User, User.id == Review.reviewer_user_id)
        .where(Review.proposal_id == p.id)
        .order_by(Review.created_at)
    ).all()
    staleness = review_service.staleness(db, p) if p.status == "pending_review" else []
    return {
        "id": p.id,
        "run_id": p.run_id,
        "version": p.version,
        "route": p.route,
        "action_kind": p.action_kind,
        "destination": p.destination,
        "payload": {k: v for k, v in p.payload.items() if k != "context_snapshot"},
        "payload_hash": p.payload_hash,
        "evidence": p.evidence,
        "evidence_hash": p.evidence_hash,
        "policy_version": p.policy_version,
        "ticket_revision": p.ticket_revision,
        "verification": p.verification,
        "verification_status": p.verification_status,
        "status": p.status,
        "authored_by": p.authored_by,
        "created_at": iso(p.created_at),
        "stale_reasons": staleness,
        "reviews": [
            {
                "id": r.id,
                "decision": r.decision,
                "reviewer": u.name,
                "binding_hash": r.binding_hash,
                "binding": r.binding,
                "note": r.note,
                "created_at": iso(r.created_at),
            }
            for r, u in reviews
        ],
    }


def graph_view(events: list[RunEvent], run: InvestigationRun) -> list[dict[str, Any]]:
    """Node states derived only from persisted runtime events."""
    started = {e.node for e in events if e.kind == "node_started" and e.node}
    done = {
        e.node
        for e in events
        if e.kind in ("node_completed", "proposal_created", "action_result", "run_finished") and e.node
    }
    if any(e.kind == "proposal_created" for e in events):
        done.add("verify")
    if any(e.kind == "awaiting_review" for e in events):
        started.add("review")
    if any(e.kind in ("action_result", "run_finished") for e in events if e.node in ("act", "audit_outcome")):
        done.add("review")
    turns = sum(1 for e in events if e.kind == "node_completed" and e.node == "investigate")
    out = []
    for key, label, kind in GRAPH_NODES:
        state = "completed" if key in done else ("active" if key in started else "pending")
        if key == "review" and run.status == "awaiting_review":
            state = "waiting"
        if run.status in ("failed", "cancelled") and state == "active":
            state = run.status
        out.append(
            {
                "id": key,
                "label": label,
                "kind": kind,
                "state": state,
                **({"turns": turns} if key == "investigate" else {}),
            }
        )
    return out


@router.post("/tickets/{ticket_id}/investigations", status_code=201)
def start(ticket_id: str, body: StartBody, p: Principal = Depends(staff_principal), db: Session = DB) -> dict[str, Any]:
    run = run_service.start_run(db, p, ticket_id, playbook_key=body.playbook_key, retrieval_mode=body.retrieval_mode)
    return run_summary(run)


@router.get("/investigations")
def list_runs(
    status: str | None = None,
    mode: str | None = None,
    ticket_id: str | None = None,
    playbook: str | None = None,
    page: int = Query(1, ge=1),
    p: Principal = Depends(staff_principal),
    db: Session = DB,
) -> dict[str, Any]:
    stmt = scoped.runs(p)
    if status:
        stmt = stmt.where(InvestigationRun.status == status)
    if mode:
        stmt = stmt.where(InvestigationRun.mode == mode)
    if ticket_id:
        stmt = stmt.where(InvestigationRun.ticket_id == ticket_id)
    if playbook:
        stmt = stmt.where(InvestigationRun.playbook_key == playbook)
    rows = list(
        db.execute(stmt.order_by(InvestigationRun.created_at.desc()).limit(50).offset((page - 1) * 50)).scalars()
    )
    tickets = {t.id: t for t in db.execute(select(Ticket).where(Ticket.id.in_({r.ticket_id for r in rows}))).scalars()}
    return {"items": [run_summary(r, tickets.get(r.ticket_id)) for r in rows], "page": page}


@router.get("/investigations/{run_id}")
def detail(run_id: str, p: Principal = Depends(staff_principal), db: Session = DB) -> dict[str, Any]:
    run = scoped.get_run(db, p, run_id)
    ticket = db.get(Ticket, run.ticket_id)
    events = list(db.execute(select(RunEvent).where(RunEvent.run_id == run.id).order_by(RunEvent.seq)).scalars())
    props = list(db.execute(select(Proposal).where(Proposal.run_id == run.id).order_by(Proposal.version)).scalars())
    acts = list(db.execute(select(ActionRecord).where(ActionRecord.run_id == run.id)).scalars())
    evidence: dict[str, Any] = {}
    for e in events:
        if e.kind == "tool_result":
            evidence.update(e.payload.get("evidence", {}))
    return {
        "run": {
            **run_summary(run, ticket),
            "budgets": run.budgets,
            "retrieval_config": run.retrieval_config,
            "policy_version": run.policy_version,
            "prompt_hash": run.prompt_hash,
            "model_digest": run.model_digest,
            "ticket_revision": run.ticket_revision,
            "thread_id": run.thread_id,
        },
        "ticket": {
            "id": ticket.id,
            "number": ticket.number,
            "subject": ticket.subject,
            "revision": ticket.revision,
            "status": ticket.status,
        }
        if ticket
        else None,
        "graph": graph_view(events, run),
        "events": [event_dict(e) for e in events],
        "evidence": evidence,
        "proposals": [proposal_dict(db, x) for x in props],
        "actions": [
            {
                "id": a.id,
                "kind": a.action_kind,
                "status": a.status,
                "adapter": a.adapter,
                "receipt": a.receipt,
                "created_at": iso(a.created_at),
            }
            for a in acts
        ],
        "last_seq": events[-1].seq if events else 0,
    }


@router.get("/investigations/{run_id}/events")
def events(run_id: str, after: int = 0, p: Principal = Depends(staff_principal), db: Session = DB) -> dict[str, Any]:
    evs = run_service.events_since(db, p, run_id, after)
    run = scoped.get_run(db, p, run_id)
    return {"events": [event_dict(e) for e in evs], "status": run.status, "last_seq": evs[-1].seq if evs else after}


@router.get("/investigations/{run_id}/stream")
async def stream(
    run_id: str,
    request: Request,
    p: Principal = Depends(staff_principal),
    last_event_id: str | None = Header(default=None),
) -> StreamingResponse:
    """SSE with sequence-based resume. Authorization is checked at connect and on every poll."""
    with new_session() as db:
        scoped.get_run(db, p, run_id)
    cursor = int(last_event_id or request.query_params.get("after", 0) or 0)

    async def gen() -> AsyncIterator[str]:
        nonlocal cursor
        idle = 0
        while not await request.is_disconnected():
            with new_session() as db:
                evs = run_service.events_since(db, p, run_id, cursor)
                status = scoped.get_run(db, p, run_id).status
            for e in evs:
                cursor = e.seq
                yield f"id: {e.seq}\nevent: run_event\ndata: {json.dumps(event_dict(e), default=str)}\n\n"
            if not evs:
                idle += 1
                if idle % 15 == 0:
                    yield ": keepalive\n\n"
            if status in run_service.TERMINAL and not evs:
                yield f"event: end\ndata: {json.dumps({'status': status})}\n\n"
                return
            await asyncio.sleep(1.0)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})


@router.post("/investigations/{run_id}/cancel")
def cancel(run_id: str, p: Principal = Depends(staff_principal), db: Session = DB) -> dict[str, Any]:
    return run_summary(run_service.cancel_run(db, p, run_id))


@router.post("/investigations/{run_id}/retry")
def retry(run_id: str, p: Principal = Depends(staff_principal), db: Session = DB) -> dict[str, Any]:
    return run_summary(run_service.retry_run(db, p, run_id))


@router.post("/investigations/{run_id}/replay", status_code=201)
def replay(run_id: str, p: Principal = Depends(staff_principal), db: Session = DB) -> dict[str, Any]:
    return run_summary(run_service.recorded_replay(db, p, run_id))


@router.post("/investigations/{run_id}/compare", status_code=201)
def compare(run_id: str, body: StartBody, p: Principal = Depends(staff_principal), db: Session = DB) -> dict[str, Any]:
    """A new live run with changed configuration. It needs its own fresh review; old approvals never carry over."""
    src = scoped.get_run(db, p, run_id)
    run = run_service.start_run(
        db,
        p,
        src.ticket_id,
        playbook_key=body.playbook_key or src.playbook_key,
        retrieval_mode=body.retrieval_mode,
        compare_of_run_id=src.id,
    )
    return run_summary(run)


@router.post("/proposals/{proposal_id}/edit")
def edit(proposal_id: str, body: EditBody, p: Principal = Depends(staff_principal), db: Session = DB) -> dict[str, Any]:
    new = review_service.edit_proposal(
        db, p, proposal_id, customer_reply=body.customer_reply, expected_version=body.expected_version, note=body.note
    )
    return proposal_dict(db, new)


@router.post("/proposals/{proposal_id}/approve")
def approve(
    proposal_id: str, body: ApproveBody, p: Principal = Depends(staff_principal), db: Session = DB
) -> dict[str, Any]:
    r = review_service.approve(
        db,
        p,
        proposal_id,
        expected_version=body.expected_version,
        expected_payload_hash=body.expected_payload_hash,
        note=body.note,
    )
    return {
        "review_id": r.id,
        "binding_hash": r.binding_hash,
        "status": "approved",
        "note": "Queued for execution by the worker; the action runs once.",
    }


@router.post("/proposals/{proposal_id}/reject")
def reject(
    proposal_id: str, body: RejectBody, p: Principal = Depends(staff_principal), db: Session = DB
) -> dict[str, Any]:
    r = review_service.reject(db, p, proposal_id, expected_version=body.expected_version, note=body.note)
    return {"review_id": r.id, "status": "rejected"}
