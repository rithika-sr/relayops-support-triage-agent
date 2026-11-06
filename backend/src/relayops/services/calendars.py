"""The organization's service calendar: versions, the active version, and due-time previews."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from relayops.domain.calendars import Calendar, CalendarError, add_service_time, validate
from relayops.domain.scope import Principal, ValidationFailed
from relayops.models import Organization, ServiceCalendarVersion
from relayops.repositories import scoped
from relayops.services import audit

NAME = "default"


def to_domain(row: ServiceCalendarVersion) -> Calendar:
    weekly, holidays = validate(row.timezone, row.weekly, row.holidays)
    return Calendar(row.name, row.version, row.timezone, weekly, holidays)


def active(db: Session, organization_id: str) -> tuple[Calendar, ServiceCalendarVersion] | None:
    row = (
        db.execute(
            select(ServiceCalendarVersion)
            .where(
                ServiceCalendarVersion.organization_id == organization_id,
                ServiceCalendarVersion.name == NAME,
                ServiceCalendarVersion.active.is_(True),
            )
            .order_by(ServiceCalendarVersion.version.desc())
        )
        .scalars()
        .first()
    )
    return (to_domain(row), row) if row else None


def as_dict(row: ServiceCalendarVersion) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "version": row.version,
        "ref": f"{row.name}@v{row.version}",
        "timezone": row.timezone,
        "weekly": row.weekly,
        "holidays": row.holidays,
        "applies_to_urgent": row.applies_to_urgent,
        "active": row.active,
        "created_at": row.created_at.isoformat(),
    }


def versions(db: Session, p: Principal) -> list[dict[str, Any]]:
    scoped.require_staff(p)
    rows = db.execute(
        select(ServiceCalendarVersion)
        .where(ServiceCalendarVersion.organization_id == p.organization_id)
        .order_by(ServiceCalendarVersion.version.desc())
    ).scalars()
    return [as_dict(r) for r in rows]


def create_version(
    db: Session, p: Principal, *, timezone: str, weekly: dict[str, Any], holidays: list[str], applies_to_urgent: bool
) -> ServiceCalendarVersion:
    scoped.require_admin(p)
    try:
        clean, days = validate(timezone, weekly, holidays)
    except CalendarError as exc:
        raise ValidationFailed(str(exc)) from exc
    db.get(Organization, p.organization_id, with_for_update=True)  # serialize version numbering per organization
    latest = db.execute(
        select(func.coalesce(func.max(ServiceCalendarVersion.version), 0)).where(
            ServiceCalendarVersion.organization_id == p.organization_id, ServiceCalendarVersion.name == NAME
        )
    ).scalar_one()
    db.execute(
        update(ServiceCalendarVersion)
        .where(ServiceCalendarVersion.organization_id == p.organization_id)
        .values(active=False)
    )
    row = ServiceCalendarVersion(
        organization_id=p.organization_id,
        name=NAME,
        version=latest + 1,
        timezone=timezone,
        weekly={k: [list(w) for w in v] for k, v in clean.items()},
        holidays=sorted(d.isoformat() for d in days),
        applies_to_urgent=applies_to_urgent,
        created_by_user_id=p.user_id,
    )
    db.add(row)
    db.flush()
    audit.record(
        db,
        organization_id=p.organization_id,
        actor=p,
        action="calendar.version_created",
        target_type="service_calendar",
        target_id=row.id,
        detail={"version": row.version, "timezone": timezone},
    )
    return row


def deactivate(db: Session, p: Principal) -> None:
    """Return to 24/7 targets. Existing tickets keep the due time and version they were given."""
    scoped.require_admin(p)
    db.execute(
        update(ServiceCalendarVersion)
        .where(ServiceCalendarVersion.organization_id == p.organization_id)
        .values(active=False)
    )
    audit.record(
        db,
        organization_id=p.organization_id,
        actor=p,
        action="calendar.deactivated",
        target_type="organization",
        target_id=p.organization_id,
    )


def preview(db: Session, p: Principal, *, start: datetime, hours: float) -> dict[str, Any]:
    scoped.require_staff(p)
    cur = active(db, p.organization_id)
    if cur is None:
        return {"calendar": None, "due_at": (start + timedelta(hours=hours)).isoformat(), "basis": "24/7 elapsed hours"}
    cal, _ = cur
    due = add_service_time(cal, start, timedelta(hours=hours))
    return {
        "calendar": cal.ref,
        "timezone": cal.timezone,
        "due_at": due.isoformat(),
        "due_local": due.astimezone(cal.tz).isoformat(),
        "basis": "service hours",
    }
