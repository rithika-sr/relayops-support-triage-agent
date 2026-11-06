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


def _agent_run(creds, ticket, script):
    use_script(script)
    cust, support = client(CUSTOMER, creds), client(SUPPORT, creds)
    tid = cust.post("/api/tickets", json=ticket).json()["ticket"]["id"]
    from relayops.services import runs
    from tests.factories import principal

    with new_session() as s:
        run = runs.start_run(s, principal(s, SUPPORT), tid, execution="agent")
        s.commit()
        run_id = run.id
    drain()
    return support.get(f"/api/investigations/{run_id}").json()


def _extract(version, code, component):
    def script(purpose, user):
        if purpose == "extract":
            return {
                "intent": "bug",
                "component": component,
                "product_version": version,
                "error_code": code,
                "first_seen": None,
                "summary": "reported failure",
            }
        if purpose == "investigate":
            return {"purpose": "Enough evidence.", "action": "finish", "tool_calls": []}
        if purpose == "propose":
            script.propose_prompt = user
            return {
                "route": "clarification",
                "rationale": "fixture",
                "evidence_ids": [],
                "missing_facts": [],
                "clarifying_questions": ["When did it start?"],
                "observations": [],
                "hypotheses": [],
            }
        if purpose == "draft_reply":
            return {"reply": "Thanks, could you tell us when this started?", "evidence_ids": []}
        return {}

    return script


def test_adaptive_path_sees_trusted_incident_as_evidence_and_signal(db, tmp_path):
    creds = seeded(db, tmp_path)
    script = _extract("2.4", "SLACK_DELIVERY_DELAY", "notifications")
    d = _agent_run(
        creds,
        {
            "subject": "Slack alerts late",
            "body": "Slack notifications are delayed (SLACK_DELIVERY_DELAY).",
            "component": "notifications",
            "product_version": "2.4",
            "error_code": "SLACK_DELIVERY_DELAY",
        },
        script,
    )
    assert any(e["source_type"] == "incident" for e in _ev(d))
    assert "trusted record lookup: reported signature SLACK_DELIVERY_DELAY" in script.propose_prompt
    assert "1 active reviewed incident(s)" in script.propose_prompt
    lookup = next(e for e in d["events"] if e["kind"] == "trusted_lookup")
    assert lookup["payload"]["applied"] is False  # the adaptive path still chooses its own route


def test_adaptive_path_near_miss_version_adds_no_issue_evidence(db, tmp_path):
    creds = seeded(db, tmp_path)
    script = _extract("2.5", "EXPORT_500", "exports")
    d = _agent_run(
        creds,
        {
            "subject": "Small exports fail",
            "body": "EXPORT_500 on 2.5 for tiny exports.",
            "component": "exports",
            "product_version": "2.5",
            "error_code": "EXPORT_500",
        },
        script,
    )
    assert not any(e["source_type"] == "issue" for e in _ev(d))  # ENG-101 is 2.4 only
    assert "0 issue(s) matching signature and version" in script.propose_prompt


def _ev(d):
    ev = d["evidence"]
    return list(ev.values()) if isinstance(ev, dict) else ev


def test_signature_lookup_finds_incidents_beyond_the_browsing_limit(db, tmp_path):
    """The seeded world has more than five active incidents; SAML_IDP_TIMEOUT is one of the older ones."""
    seeded(db, tmp_path)
    from relayops.services import diagnostics

    with new_session() as s:
        browsing = diagnostics.incident_snapshot(s, "org_taskflow", as_of=utcnow(), component=None)
        _, d = _decide(s, account="acct_northstar", version="2.5", code="SAML_IDP_TIMEOUT")
    assert len(browsing) == 5 and all(i["error_signature"] != "SAML_IDP_TIMEOUT" for i in browsing)
    assert d.route == "incident_link" and d.incident["id"] == "inc_saml_idp"


def test_bug_playbook_can_link_a_reviewed_incident_but_not_without_one(db, tmp_path):
    """A failure report with an error code gets the bug playbook; it must be able to link a matching incident."""
    seeded(db, tmp_path)
    bug = DEFAULT_PLAYBOOKS["bug"]["config"]["allowed_routes"]
    with new_session() as s:
        facts = policy.gather(
            s,
            organization_id="org_taskflow",
            customer_account_id="acct_northstar",
            as_of=utcnow(),
            component="sso",
            version="2.5",
            error_code="SAML_IDP_TIMEOUT",
            text="",
            entitlements=entitlements_for("business"),
        )
        near = policy.gather(
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
    assert policy.decide(facts, restricted=False, allowed_routes=bug).route == "incident_link"
    assert policy.decide(near, restricted=False, allowed_routes=bug).route == "link_existing_issue"  # no incident


def test_disallowed_model_route_asks_the_customer_instead_of_restricting(db, tmp_path):
    """A vague how-to ticket must not land in the restricted specialist queue because the model picked a bad route."""
    creds = seeded(db, tmp_path)

    def script(purpose, user):
        if purpose == "extract":
            return {
                "intent": "how_to",
                "component": None,
                "product_version": None,
                "error_code": None,
                "first_seen": None,
                "summary": "vague",
            }
        if purpose == "investigate":
            return {"purpose": "Enough evidence.", "action": "finish", "tool_calls": []}
        if purpose == "propose":
            return {
                "route": "new_engineering_handoff",
                "rationale": "unclear",
                "evidence_ids": [],
                "missing_facts": ["page_or_feature"],
                "clarifying_questions": ["Which page?"],
                "observations": [],
                "hypotheses": [],
            }
        if purpose == "draft_reply":
            return {"reply": "Thanks for reaching out. Which page or feature is affected?", "evidence_ids": []}
        return {}

    d = _agent_run(creds, {"subject": "Something is off", "body": "Things are not right with our account."}, script)
    prop = d["proposals"][0]
    assert prop["route"] == "clarification"
    assert any("not allowed by playbook -> clarification" in o for o in prop["payload"].get("overrides", []))
    with new_session() as s:
        from relayops.models import Ticket

        assert s.get(Ticket, d["run"]["ticket_id"]).restricted is False


def test_adaptive_path_sees_the_plan_record_for_entitlement_questions(db, tmp_path):
    creds = seeded(db, tmp_path)
    script = _extract(None, None, None)
    _agent_run(creds, {"subject": "Can we turn on SSO?", "body": "We are on Business. Can we enable SAML SSO?"}, script)
    assert "the plan record answers an entitlement question: sso = False" in script.propose_prompt
    assert "A question is not a failure report" in __import__("relayops.agents.prompts", fromlist=["x"]).PROPOSE_SYSTEM
