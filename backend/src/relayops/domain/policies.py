"""Versioned deterministic support policy: entitlements, response targets, and priority.

Targets are 24/7 elapsed hours. There is no business-hours calendar in this version.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

POLICY_VERSION = "2026.11-r1"

PLANS = ("starter", "team", "business", "enterprise")
PRIORITIES = ("low", "normal", "high", "urgent")

# First-response targets in elapsed hours, by plan then priority.
FIRST_RESPONSE_HOURS: dict[str, dict[str, int]] = {
    "starter": {"low": 72, "normal": 48, "high": 24, "urgent": 24},
    "team": {"low": 48, "normal": 24, "high": 12, "urgent": 8},
    "business": {"low": 24, "normal": 12, "high": 4, "urgent": 2},
    "enterprise": {"low": 12, "normal": 8, "high": 2, "urgent": 1},
}

# Entitlements effective under the current policy version. SSO moved to Enterprise-only on
# 2026-07-01 (see the sso-entitlement policy document); earlier Business-plan guidance is obsolete.
ENTITLEMENTS: dict[str, dict[str, Any]] = {
    "starter": {"sso": False, "scim": False, "webhooks": False, "export_row_limit": 10_000, "audit_log_days": 7},
    "team": {"sso": False, "scim": False, "webhooks": True, "export_row_limit": 50_000, "audit_log_days": 30},
    "business": {"sso": False, "scim": False, "webhooks": True, "export_row_limit": 250_000, "audit_log_days": 90},
    "enterprise": {"sso": True, "scim": True, "webhooks": True, "export_row_limit": 1_000_000, "audit_log_days": 365},
}

COMPONENTS = ("exports", "sso", "webhooks", "billing", "notifications", "api", "projects", "integrations")

_URGENT_WORDS = re.compile(r"\b(outage|down for everyone|all users|cannot log ?in|data loss|production down)\b", re.I)
_SECURITY_WORDS = re.compile(
    r"\b(security (issue|vulnerability|incident|bug|hole|problem|report|flaw)|vulnerab\w*|exploit\w*|breach\w*|"
    r"leak(ed|ing)? (token|key|password|credential|data)\w*|unauthori[sz]ed access|"
    r"exposed (data|token|key|password|credential)\w*|xss|csrf|sql injection|account takeover)\b",
    re.I,
)


@dataclass(frozen=True)
class TargetDecision:
    priority: str
    due_at: datetime
    hours: int
    reasons: tuple[str, ...]
    urgent_review: bool
    restricted: bool

    def as_policy(self) -> dict[str, Any]:
        return {
            "policy_version": POLICY_VERSION,
            "priority": self.priority,
            "hours": self.hours,
            "basis": "24/7 elapsed hours",
            "reasons": list(self.reasons),
            "urgent_review": self.urgent_review,
            "restricted": self.restricted,
        }


def entitlements_for(plan: str) -> dict[str, Any]:
    if plan not in ENTITLEMENTS:
        raise ValueError(f"unknown plan {plan}")
    return dict(ENTITLEMENTS[plan])


def is_security_sensitive(text: str) -> bool:
    return bool(_SECURITY_WORDS.search(text))


def decide_target(
    *, plan: str, reported_severity: str, subject: str, body: str, created_at: datetime
) -> TargetDecision:
    """Priority comes from the customer's stated severity plus plan, never from sentiment alone.

    Critical customer language raises the ticket to urgent *review*; it does not make it a confirmed outage.
    """
    if created_at.tzinfo is None:
        raise ValueError("created_at must be timezone-aware UTC")
    text = f"{subject}\n{body}"
    reasons: list[str] = []
    severity = reported_severity if reported_severity in PRIORITIES else "normal"
    if reported_severity == "critical":
        severity = "urgent"
    priority = severity
    reasons.append(f"customer-reported severity: {reported_severity}")
    urgent_review = False
    if _URGENT_WORDS.search(text):
        urgent_review = True
        reasons.append("customer describes critical impact (unverified)")
        if PRIORITIES.index(priority) < PRIORITIES.index("high"):
            priority = "high"
    restricted = is_security_sensitive(text)
    if restricted:
        reasons.append("security-sensitive language: restricted specialist review")
        if PRIORITIES.index(priority) < PRIORITIES.index("high"):
            priority = "high"
    hours = FIRST_RESPONSE_HOURS[plan][priority]
    reasons.append(f"{plan} plan first-response target for {priority}: {hours}h")
    return TargetDecision(
        priority=priority,
        due_at=created_at + timedelta(hours=hours),
        hours=hours,
        reasons=tuple(reasons),
        urgent_review=urgent_review,
        restricted=restricted,
    )


def target_state(due_at: datetime | None, responded_at: datetime | None, now: datetime) -> dict[str, Any]:
    if due_at is None:
        return {"state": "none"}
    if responded_at is not None:
        return {"state": "met" if responded_at <= due_at else "missed", "seconds_remaining": None}
    remaining = int((due_at - now).total_seconds())
    return {"state": "breached" if remaining < 0 else "due", "seconds_remaining": remaining}
