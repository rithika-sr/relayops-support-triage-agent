"""Record product events: validated against the versioned schema and deduplicated by event ID."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from relayops.core.clock import utcnow
from relayops.domain import events as schema
from relayops.domain.scope import Principal, ValidationFailed
from relayops.models import CustomerAccount, Organization, ProductEvent
from relayops.repositories import scoped
from relayops.services import audit

MAX_IMPORT = 5000


def record(
    db: Session,
    *,
    organization_id: str,
    name: str,
    properties: dict[str, Any],
    customer_account_id: str | None,
    actor_user_id: str | None = None,
    event_id: str | None = None,
    occurred_at: datetime | None = None,
    source: str = "app",
    data_class: str | None = None,
    schema_version: int = schema.SCHEMA_VERSION,
) -> bool:
    """Insert one event. Returns False when an event with the same ID already exists (deduplicated)."""
    props = schema.validate(name, properties, schema_version)
    if data_class is None:
        org = db.get(Organization, organization_id)
        data_class = org.data_class if org else "unknown"
    stmt = (
        insert(ProductEvent)
        .values(
            id=f"evt_{uuid.uuid4().hex[:20]}",
            organization_id=organization_id,
            customer_account_id=customer_account_id,
            event_id=(event_id or f"{name}:{uuid.uuid4().hex}")[:160],
            name=name,
            schema_version=schema_version,
            actor_user_id=actor_user_id,
            occurred_at=occurred_at or utcnow(),
            received_at=utcnow(),
            properties=props,
            source=source,
            data_class=data_class,
        )
        .on_conflict_do_nothing(index_elements=["organization_id", "event_id"])
        .returning(ProductEvent.id)
    )
    return db.execute(stmt).first() is not None


def for_principal(
    db: Session, p: Principal, name: str, properties: dict[str, Any], *, event_id: str | None = None
) -> bool:
    return record(
        db,
        organization_id=p.organization_id,
        name=name,
        properties=properties,
        customer_account_id=p.customer_account_id,
        actor_user_id=p.user_id,
        event_id=event_id,
    )


def import_events(db: Session, p: Principal, items: list[dict[str, Any]], *, dry_run: bool) -> dict[str, Any]:
    """Import events recorded elsewhere. Each needs event_id, name, occurred_at, and an account in this org."""
    scoped.require_admin(p)
    if len(items) > MAX_IMPORT:
        raise ValidationFailed(f"at most {MAX_IMPORT} events per import")
    accepted = duplicates = 0
    errors: list[dict[str, Any]] = []
    with db.begin_nested() as sp:
        for i, it in enumerate(items):
            try:
                acct = it.get("customer_account_id")
                if acct is not None:
                    a = db.get(CustomerAccount, acct)
                    if a is None or a.organization_id != p.organization_id:
                        raise ValidationFailed("customer account not found in this organization")
                if not it.get("event_id"):
                    raise ValidationFailed("event_id is required for imported events")
                when = datetime.fromisoformat(str(it["occurred_at"]))
                if when.tzinfo is None:
                    raise ValidationFailed("occurred_at must include a UTC offset")
                if when > utcnow():
                    raise ValidationFailed("occurred_at is in the future")
                created = record(
                    db,
                    organization_id=p.organization_id,
                    name=str(it.get("name", "")),
                    properties=dict(it.get("properties") or {}),
                    customer_account_id=acct,
                    event_id=f"import:{it['event_id']}",
                    occurred_at=when,
                    source="import",
                    schema_version=int(it.get("schema_version", schema.SCHEMA_VERSION)),
                )
                accepted += created
                duplicates += not created
            except (schema.EventInvalid, ValidationFailed, KeyError, ValueError, TypeError) as exc:
                errors.append({"row": i, "error": str(exc)})
        if dry_run or errors:
            sp.rollback()
    if not dry_run and not errors:
        audit.record(
            db,
            organization_id=p.organization_id,
            actor=p,
            action="events.imported",
            target_type="organization",
            target_id=p.organization_id,
            detail={"accepted": accepted, "duplicates": duplicates},
        )
    return {
        "dry_run": dry_run,
        "committed": not dry_run and not errors,
        "accepted": accepted if not errors else 0,
        "duplicates": duplicates,
        "errors": errors[:50],
        "schema_version": schema.SCHEMA_VERSION,
    }
