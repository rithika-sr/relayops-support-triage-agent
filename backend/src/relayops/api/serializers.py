"""Explicit response shapes. Customer views get a narrower projection than staff views."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from relayops.domain.scope import Principal


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
