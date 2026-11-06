from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from relayops.domain.binding import approval_binding, binding_hash, binding_mismatches
from relayops.domain.incidents import SignalTicket, group_signals, normalize_signature
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


def test_signature_normalization():
    assert normalize_signature("export-500") == "EXPORT_500"
    assert normalize_signature("req 1234567 failed") == "REQ_<N>_FAILED"


def _sig(i, acct, minutes, code="WEBHOOK_SIG_MISMATCH", version="2.5", component="webhooks"):
    return SignalTicket(f"t{i}", acct, component, code, version, T0 + timedelta(minutes=minutes))


def test_grouping_counts_distinct_accounts_and_respects_window_and_version():
    tickets = [
        _sig(1, "acme", 0),
        _sig(2, "orbit", 30),
        _sig(3, "acme", 60),
        _sig(4, "acme", 60 * 24),  # outside 6h window -> separate, alone -> dropped
        _sig(5, "north", 10, version="2.4"),  # different version
        _sig(6, "north", 20, code=None),
    ]
    groups = group_signals(tickets)
    assert len(groups) == 1
    g = groups[0]
    assert g.ticket_ids == ["t1", "t2", "t3"] and g.distinct_accounts == 2


def test_binding_detects_any_material_change():
    base = approval_binding(
        organization_id="o",
        customer_account_id="a",
        reviewer_user_id="u",
        ticket_id="t",
        ticket_revision=1,
        proposal_id="p",
        proposal_version=1,
        action_kind="post_customer_reply",
        destination={"ticket_id": "t"},
        payload_hash="h1",
        evidence_hash="e",
        policy_version="v",
    )
    changed = {**base, "ticket_revision": 2, "payload_hash": "h2"}
    assert binding_mismatches(base, changed) == ["payload_hash", "ticket_revision"]
    assert binding_hash(base) != binding_hash(changed)
    assert binding_mismatches(base, {**base, "reviewer_user_id": "other"}) == []


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
