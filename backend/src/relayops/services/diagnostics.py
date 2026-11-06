"""Allowlisted diagnostic computations over synthetic deployment and error-aggregate records.

These are fixed queries with typed parameters; nothing here executes model-supplied SQL or code.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from relayops.domain.incidents import normalize_signature
from relayops.models import Deployment, ErrorAggregate, Incident, IncidentTicketLink

STALE_AFTER = timedelta(hours=3)


def recent_deployments(
    db: Session, organization_id: str, *, as_of: datetime, component: str | None, lookback_hours: int
) -> list[dict[str, Any]]:
    since = as_of - timedelta(hours=lookback_hours)
    stmt = select(Deployment).where(
        Deployment.organization_id == organization_id, Deployment.deployed_at >= since, Deployment.deployed_at <= as_of
    )
    if component:
        stmt = stmt.where(Deployment.component == component)
    return [
        {
            "id": d.id,
            "component": d.component,
            "version": d.version,
            "deployed_at": d.deployed_at.isoformat(),
            "summary": d.summary,
            "status": d.status,
        }
        for d in db.execute(stmt.order_by(Deployment.deployed_at.desc()).limit(10)).scalars()
    ]


def error_summary(
    db: Session,
    organization_id: str,
    *,
    as_of: datetime,
    customer_account_id: str,
    component: str | None,
    signature: str | None,
    lookback_hours: int,
) -> dict[str, Any]:
    since = as_of - timedelta(hours=lookback_hours)
    sig = normalize_signature(signature)
    base = [
        ErrorAggregate.organization_id == organization_id,
        ErrorAggregate.bucket_start >= since,
        ErrorAggregate.bucket_start <= as_of,
    ]
    if component:
        base.append(ErrorAggregate.component == component)
    if sig:
        base.append(ErrorAggregate.error_signature == sig)
    rows = db.execute(
        select(
            ErrorAggregate.error_signature,
            ErrorAggregate.component,
            ErrorAggregate.product_version,
            func.sum(ErrorAggregate.count),
            func.count(func.distinct(ErrorAggregate.customer_account_id)),
            func.min(ErrorAggregate.bucket_start),
            func.max(ErrorAggregate.bucket_start),
        )
        .where(*base)
        .group_by(ErrorAggregate.error_signature, ErrorAggregate.component, ErrorAggregate.product_version)
        .order_by(func.sum(ErrorAggregate.count).desc())
        .limit(5)
    ).all()
    series = []
    for s, comp, ver, total, accounts, first, last in rows:
        mine = db.execute(
            select(func.sum(ErrorAggregate.count), func.min(ErrorAggregate.bucket_start)).where(
                *base, ErrorAggregate.error_signature == s, ErrorAggregate.customer_account_id == customer_account_id
            )
        ).one()
        series.append(
            {
                "signature": s,
                "component": comp,
                "product_version": ver,
                "total_errors": int(total),
                "distinct_accounts": int(accounts),
                "first_seen": first.isoformat(),
                "last_seen": last.isoformat(),
                "this_account_errors": int(mine[0] or 0),
                "this_account_first_seen": mine[1].isoformat() if mine[1] else None,
            }
        )
    latest = db.execute(
        select(func.max(ErrorAggregate.bucket_start)).where(ErrorAggregate.organization_id == organization_id)
    ).scalar_one()
    stale = latest is None or latest < as_of - STALE_AFTER
    return {
        "window": {"from": since.isoformat(), "to": as_of.isoformat()},
        "series": series,
        "feed_latest_bucket": latest.isoformat() if latest else None,
        "stale": stale,
    }


def incident_snapshot(
    db: Session,
    organization_id: str,
    *,
    as_of: datetime,
    component: str | None,
    signature: str | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Active (or recently resolved) incidents. With a signature, every incident with that signature is returned:
    an exact lookup must not be cut off by the recency limit used for browsing."""
    stmt = select(Incident).where(
        Incident.organization_id == organization_id,
        Incident.started_at <= as_of,
        (Incident.resolved_at.is_(None)) | (Incident.resolved_at >= as_of - timedelta(hours=72)),
    )
    if component:
        stmt = stmt.where(Incident.component == component)
    if signature:
        stmt = stmt.where(Incident.error_signature == signature)
    stmt = stmt.order_by(Incident.started_at.desc())
    out = []
    for i in db.execute(stmt if signature else stmt.limit(limit)).scalars():
        linked = db.execute(
            select(func.count(IncidentTicketLink.id)).where(IncidentTicketLink.incident_id == i.id)
        ).scalar_one()
        out.append(
            {
                "id": i.id,
                "title": i.title,
                "component": i.component,
                "status": i.status,
                "severity": i.severity,
                "started_at": i.started_at.isoformat(),
                "resolved_at": i.resolved_at.isoformat() if i.resolved_at else None,
                "error_signature": i.error_signature,
                "affected_versions": i.affected_versions,
                "public_visible": i.public_visible,
                "public_summary": i.public_summary if i.public_visible else None,
                "linked_tickets": int(linked),
            }
        )
    return out
