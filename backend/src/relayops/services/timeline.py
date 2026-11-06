"""Diagnostic evidence timeline for a ticket.

Lanes keep sources separate: what the customer reported, trusted records (deployments, incidents, issue
state, document versions, error aggregates), and hypotheses proposed during investigation. Every item names
its source snapshot and as-of time. Temporal proximity is labeled as correlation, never as cause.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from relayops.domain.scope import Principal
from relayops.models import InvestigationRun, Proposal, RunEvent, TicketMessage
from relayops.repositories import scoped

LANE_BY_SOURCE = {
    "deployment": "trusted_record",
    "incident": "trusted_record",
    "issue": "trusted_record",
    "knowledge": "trusted_record",
    "case": "trusted_record",
    "error_aggregate": "signal",
}


def ticket_timeline(db: Session, p: Principal, ticket_id: str) -> dict[str, Any]:
    scoped.require_staff(p)
    ticket = scoped.get_ticket(db, p, ticket_id)
    items: list[dict[str, Any]] = []
    for m in db.execute(scoped.messages(p, ticket.id)).scalars():
        lane = "customer_report" if m.author_kind == "customer" else "staff"
        items.append(
            {
                "at": m.created_at.isoformat(),
                "lane": lane,
                "kind": f"message_{m.visibility}",
                "label": m.body[:160],
                "source": f"message:{m.id}",
                "as_of": m.created_at.isoformat(),
            }
        )
    run_ids = [
        r.id
        for r in db.execute(
            scoped.runs(p).where(InvestigationRun.ticket_id == ticket.id, InvestigationRun.mode == "live")
        ).scalars()
    ]
    seen: set[str] = set()
    for ev in db.execute(
        select(RunEvent).where(RunEvent.run_id.in_(run_ids), RunEvent.kind == "tool_result").order_by(RunEvent.seq)
    ).scalars():
        for eid, e in (ev.payload.get("evidence") or {}).items():
            key = f"{e['source_type']}:{e['source_id']}:{e.get('version')}"
            if key in seen or not e.get("timestamp"):
                continue
            seen.add(key)
            label = e["title"]
            note = None
            if e["source_type"] == "deployment":
                note = "temporal correlation only; not a confirmed cause"
            if e["source_type"] == "error_aggregate":
                label = f"{e['title']}: first seen (organization-wide)"
                mine = e["meta"].get("this_account_first_seen")
                if mine:
                    items.append(
                        {
                            "at": mine,
                            "lane": "signal",
                            "kind": "errors_first_seen_account",
                            "label": f"{e['meta']['signature']} first seen for this account",
                            "source": e["source_id"],
                            "as_of": ev.created_at.isoformat(),
                            "run_id": ev.run_id,
                        }
                    )
            if e["source_type"] in ("knowledge", "case"):
                label = f"{e['title']} (v{e.get('version')}) valid from"
            if e["source_type"] == "issue":
                label = f"{e['title']} last updated (status {e['meta'].get('status')})"
            items.append(
                {
                    "at": e["timestamp"],
                    "lane": LANE_BY_SOURCE.get(e["source_type"], "trusted_record"),
                    "kind": e["source_type"],
                    "label": label,
                    "source": f"{e['source_type']}:{e['source_id']}",
                    "snapshot_hash": e.get("snapshot_hash"),
                    "as_of": ev.created_at.isoformat(),
                    "run_id": ev.run_id,
                    "evidence_id": eid,
                    **({"note": note} if note else {}),
                }
            )
            if e["source_type"] == "incident" and e["meta"].get("resolved_at"):
                items.append(
                    {
                        "at": e["meta"]["resolved_at"],
                        "lane": "trusted_record",
                        "kind": "incident_resolved",
                        "label": f"{e['title']} resolved",
                        "source": f"incident:{e['source_id']}",
                        "as_of": ev.created_at.isoformat(),
                    }
                )
    for prop in db.execute(select(Proposal).where(Proposal.run_id.in_(run_ids)).order_by(Proposal.version)).scalars():
        for h in prop.payload.get("hypotheses") or []:
            items.append(
                {
                    "at": prop.created_at.isoformat(),
                    "lane": "hypothesis",
                    "kind": "hypothesis",
                    "label": h,
                    "source": f"proposal:{prop.id}",
                    "as_of": prop.created_at.isoformat(),
                    "note": "unconfirmed",
                }
            )
    items.sort(key=lambda x: (x["at"], x["lane"]))
    first_customer = (
        db.execute(
            select(TicketMessage.created_at)
            .where(TicketMessage.ticket_id == ticket.id)
            .order_by(TicketMessage.created_at)
        )
        .scalars()
        .first()
    )
    return {
        "ticket_id": ticket.id,
        "reported_at": first_customer.isoformat() if first_customer else None,
        "items": items,
        "legend": {
            "customer_report": "What the customer said",
            "trusted_record": "Persisted records",
            "signal": "Computed from synthetic aggregates",
            "hypothesis": "Unconfirmed proposals",
            "staff": "Staff messages and notes",
        },
    }
