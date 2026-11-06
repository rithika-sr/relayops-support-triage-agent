from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from relayops.domain.policies import decide_target, entitlements_for, target_state
from relayops.domain.scope import Principal

T0 = datetime(2026, 11, 6, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    ("plan", "severity", "hours"),
    [("starter", "normal", 48), ("team", "high", 12), ("business", "normal", 12), ("enterprise", "critical", 1)],
)
def test_first_response_targets_are_elapsed_hours(plan, severity, hours):
    d = decide_target(plan=plan, reported_severity=severity, subject="Question", body="How do I export?", created_at=T0)
    assert d.hours == hours and d.due_at == T0 + timedelta(hours=hours)


def test_critical_language_triggers_urgent_review_not_outage():
    d = decide_target(
        plan="team",
        reported_severity="low",
        subject="Production down for everyone",
        body="all users affected",
        created_at=T0,
    )
    assert d.urgent_review and d.priority == "high"
    assert "unverified" in " ".join(d.reasons)


def test_naive_datetime_rejected():
    with pytest.raises(ValueError):
        decide_target(plan="team", reported_severity="low", subject="x", body="y", created_at=datetime(2026, 1, 1))


def test_sso_entitlement_is_enterprise_only():
    assert entitlements_for("business")["sso"] is False
    assert entitlements_for("enterprise")["sso"] is True


def test_target_state():
    assert target_state(T0, None, T0 + timedelta(hours=1))["state"] == "breached"
    assert target_state(T0, T0 - timedelta(minutes=5), T0)["state"] == "met"
    assert target_state(T0 + timedelta(hours=2), None, T0)["seconds_remaining"] == 7200


def test_customer_principal_requires_account():
    with pytest.raises(ValueError):
        Principal(
            user_id="u",
            email="e",
            name="n",
            membership_id="m",
            organization_id="o",
            role="customer",
            customer_account_id=None,
        )


@pytest.mark.parametrize(
    ("text", "restricted"),
    [
        ("Can we enable SSO from Settings > Security?", False),
        ("Our security team wants an audit log export", False),
        ("I found a security vulnerability in comments (XSS)", True),
        ("An API token was exposed in a public screenshot: leaked token", True),
        ("Possible unauthorized access to our workspace", True),
    ],
)
def test_security_sensitivity_rule(text, restricted):
    from relayops.domain.policies import is_security_sensitive

    assert is_security_sensitive(text) is restricted
