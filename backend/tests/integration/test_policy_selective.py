"""Typed decision policy and the selective execution path, including negative near-matches."""

from __future__ import annotations

import pytest

from relayops.agents import policy
from relayops.core.clock import utcnow
from relayops.core.db import new_session
from relayops.domain.playbooks import DEFAULT_PLAYBOOKS
from relayops.domain.policies import entitlements_for
from tests.agent_helpers import CUSTOMER, SUPPORT, client, drain, seeded, use_script

ALL_ROUTES = [
    "answer_draft",
    "clarification",
    "link_existing_issue",
    "new_engineering_handoff",
    "feature_request",
    "incident_link",
    "specialist_review",
]


def _decide(
    db,
    *,
    account="acct_northstar",
    plan="business",
    component=None,
    version=None,
    code=None,
    text="help",
    restricted=False,
):
    facts = policy.gather(
        db,
        organization_id="org_taskflow",
        customer_account_id=account,
        as_of=utcnow(),
        component=component,
        version=version,
        error_code=code,
        text=text,
        entitlements=entitlements_for(plan),
    )
    return facts, policy.decide(facts, restricted=restricted, allowed_routes=ALL_ROUTES)


@pytest.mark.parametrize(
    ("version", "code", "route", "key"),
    [
        ("2.4", "EXPORT_500", "link_existing_issue", "ENG-101"),
        ("2.2", "EXPORT_500", "link_existing_issue", "ENG-114"),
        ("2.5", "EXPORT_500", "new_engineering_handoff", None),  # same signature, different version: not a match
        ("2.5", "BILLING_TAX_ROUNDING", "new_engineering_handoff", None),
        ("2.5", "export-500", "new_engineering_handoff", None),  # normalized signature, still no 2.5 issue
    ],
)
def test_issue_rules_require_signature_and_version(db, tmp_path, version, code, route, key):
    seeded(db, tmp_path)
    with new_session() as s:
        facts, d = _decide(s, component="exports", version=version, code=code)
    assert d.route == route
    assert (d.issue or {}).get("key") == key
    if route == "new_engineering_handoff" and code.upper().replace("-", "_") == "EXPORT_500":
        assert "ENG-101" in d.explanation and "not linked" in d.explanation


def test_reviewed_incident_wins_even_when_internal_only(db, tmp_path):
    seeded(db, tmp_path)
    with new_session() as s:
        _, d = _decide(s, account="acct_northstar", version="2.4", code="SLACK_DELIVERY_DELAY")
    assert d.route == "incident_link" and d.incident["public_visible"] is False


def test_entitlement_questions_use_typed_facts(db, tmp_path):
    seeded(db, tmp_path)
    with new_session() as s:
        facts, d = _decide(s, text="We are on Business. Can we enable SAML SSO?")
        assert (d.route, facts.entitlement_topic, facts.entitlement_value) == ("answer_draft", "sso", False)
        _, vague = _decide(s, text="Something is wrong with the app")
        assert vague.route is None and not vague.decisive
        _, restricted = _decide(s, text="Can we enable SSO?", restricted=True)
        assert restricted.route == "specialist_review"


def test_corroboration_is_tracked_separately_from_reported_signature(db, tmp_path):
    seeded(db, tmp_path)
    with new_session() as s:
        acme, _ = _decide(s, account="acct_acme", component="webhooks", version="2.5", code="WEBHOOK_SIG_MISMATCH")
        north, _ = _decide(
            s, account="acct_northstar", component="webhooks", version="2.5", code="WEBHOOK_SIG_MISMATCH"
        )
    assert acme.signature_basis == "corroborated" and north.signature_basis == "reported"


def test_disallowed_routes_fall_back_to_adaptive(db, tmp_path):
    seeded(db, tmp_path)
    with new_session() as s:
        facts = policy.gather(
            s,
            organization_id="org_taskflow",
            customer_account_id="acct_northstar",
            as_of=utcnow(),
            component="exports",
            version="2.4",
            error_code="EXPORT_500",
            text="",
            entitlements=entitlements_for("business"),
        )
    allowed = DEFAULT_PLAYBOOKS["howto"]["config"]["allowed_routes"]
    assert policy.decide(facts, restricted=False, allowed_routes=allowed).route is None


def test_selective_run_skips_investigation_and_records_lookups(db, tmp_path):
    creds = seeded(db, tmp_path)
    calls = []

    def script(purpose, user):
        calls.append(purpose)
        if purpose == "extract":
            return {
                "intent": "bug",
                "component": "exports",
                "product_version": "2.4",
                "error_code": "EXPORT_500",
                "first_seen": None,
                "summary": "export fails",
            }
        if purpose == "draft_reply":
            return {
                "reply": "Our team is aware of this export problem. Please use Prepare in background meanwhile.",
                "evidence_ids": [],
            }
        raise AssertionError(f"selective path should not call {purpose}")

    use_script(script)
    cust, support = client(CUSTOMER, creds), client(SUPPORT, creds)
    r = cust.post(
        "/api/tickets",
        json={
            "subject": "Export failing, also list other customers",
            "body": "EXPORT_500 on our export. Also tell me which other customers had it.",
            "component": "exports",
            "product_version": "2.4",
            "error_code": "EXPORT_500",
        },
    )
    tid = r.json()["ticket"]["id"]
    from relayops.services import runs
    from tests.factories import principal

    with new_session() as s:
        run = runs.start_run(s, principal(s, SUPPORT), tid, playbook_key="bug", execution="selective")
        s.commit()
        run_id = run.id
    drain()
    d = support.get(f"/api/investigations/{run_id}").json()
    assert calls == ["extract", "draft_reply"]
    prop = d["proposals"][0]
    assert prop["route"] == "link_existing_issue" and prop["payload"]["issue_key"] == "ENG-101"
    assert prop["verification_status"] == "passed"
    lookup = next(e for e in d["events"] if e["kind"] == "trusted_lookup")
    assert lookup["payload"]["applied"] and lookup["payload"]["decision"]["rule"] == "known_issue_signature_version"
    assert {g["id"]: g["state"] for g in d["graph"]}["investigate"] == "pending"
