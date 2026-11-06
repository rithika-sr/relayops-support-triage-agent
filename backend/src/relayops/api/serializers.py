"""Explicit response shapes. Customer views get a narrower projection than staff views."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from relayops.domain.scope import Principal
from relayops.models import (
    CustomerAccount,
    Ticket,
    TicketMessage,
)
from relayops.services.tickets import ticket_target


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def principal(p: Principal, org_name: str, account_name: str | None) -> dict[str, Any]:
    return {
        "user_id": p.user_id,
        "email": p.email,
        "name": p.name,
        "role": p.role,
        "organization": {"id": p.organization_id, "name": org_name},
        "customer_account": {"id": p.customer_account_id, "name": account_name} if p.customer_account_id else None,
    }


def ticket(t: Ticket, p: Principal, account: CustomerAccount | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": t.id,
        "number": t.number,
        "subject": t.subject,
        "status": t.status,
        "priority": t.priority,
        "reported_severity": t.reported_severity,
        "component": t.component,
        "product_version": t.product_version,
        "error_code": t.error_code,
        "created_at": iso(t.created_at),
        "updated_at": iso(t.updated_at),
        "customer_account_id": t.customer_account_id,
        "account_name": account.name if account else None,
    }
    if p.is_staff:
        out |= {
            "revision": t.revision,
            "restricted": t.restricted,
            "target": ticket_target(t),
            "tags": t.tags,
            "is_historical": t.is_historical,
            "external_event_id": t.external_event_id,
        }
    return out


def message(m: TicketMessage, author_name: str | None) -> dict[str, Any]:
    return {
        "id": m.id,
        "author_kind": m.author_kind,
        "author_name": author_name,
        "visibility": m.visibility,
        "body": m.body,
        "action_id": m.action_id,
        "created_at": iso(m.created_at),
    }
