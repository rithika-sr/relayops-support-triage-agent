from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from relayops.domain.scope import Principal
from relayops.models import AuditEvent
from relayops.repositories.scoped import require_admin


def record(
    db: Session,
    *,
    organization_id: str,
    action: str,
    target_type: str,
    target_id: str,
    actor: Principal | None = None,
    actor_kind: str | None = None,
    outcome: str = "ok",
    detail: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        organization_id=organization_id,
        actor_user_id=actor.user_id if actor else None,
        actor_kind=actor_kind or ("user" if actor else "system"),
        action=action,
        target_type=target_type,
        target_id=target_id,
        outcome=outcome,
        detail=detail or {},
    )
    db.add(event)
    return event


def list_events(
    db: Session,
    p: Principal,
    *,
    action: str | None = None,
    outcome: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[AuditEvent]:
    require_admin(p)
    stmt = select(AuditEvent).where(AuditEvent.organization_id == p.organization_id)
    if action:
        stmt = stmt.where(AuditEvent.action.like(f"{action}%"))
    if outcome:
        stmt = stmt.where(AuditEvent.outcome == outcome)
    stmt = stmt.order_by(AuditEvent.created_at.desc(), AuditEvent.id).limit(min(limit, 500)).offset(offset)
    return list(db.execute(stmt).scalars())
