"""Verification checks and simulated external connector outcomes."""

from __future__ import annotations

from relayops.agents.verification import verify
from relayops.core.db import new_session
from relayops.domain.policies import entitlements_for
from relayops.models import ActionRecord
from relayops.services import actions
from tests.agent_helpers import seeded

CTX = {
    "account": {"plan": "business", "entitlements": entitlements_for("business")},
    "ticket": {"product_version": "2.4"},
}
PUBLIC = {
    "E1": {
        "source_type": "knowledge",
        "visibility": "public",
        "excerpt": "SSO is included only in the Enterprise plan.",
        "meta": {"document_id": "x", "document_version_id": "y"},
    }
}
INTERNAL = {"E2": {"source_type": "issue", "visibility": "internal", "excerpt": "ENG-101 memory", "meta": {}}}


def _v(db, reply, cites=(), kind="post_customer_reply", evidence=None, **payload):
    return verify(
        db,
        organization_id="org_taskflow",
        customer_account_id="acct_northstar",
        action_kind=kind,
        payload={"customer_reply": reply, "reply_evidence_ids": list(cites), **payload},
        evidence=evidence or {},
        context=CTX,
    )


def test_typed_and_policy_checks(db, tmp_path):
    seeded(db, tmp_path)
    with new_session() as s:
        sso = _v(s, "Good news: SSO is included in your Business plan, you can enable it in Settings.")
        assert "entitlement_sso" in sso["failed"]
        ok = _v(s, "SSO is not included in the Business plan; it requires Enterprise.")
        assert "entitlement_sso" not in ok["failed"]
        leak = _v(s, "This is tracked as ENG-101 by data-platform and also affects Acme Robotics.")
        assert "no_internal_disclosure" in leak["failed"]
        cause = _v(s, "The failure was caused by the deployment on Monday.")
        assert "no_unsupported_root_cause" in cause["failed"]
        outage = _v(s, "There is a confirmed outage affecting everyone.")
        assert "no_unconfirmed_outage" in outage["failed"]
        internal = _v(s, "We looked into this for you carefully.", cites=["E2"], evidence=INTERNAL)
        assert "reply_visibility" in internal["failed"]
        ghost = _v(s, "We looked into this for you carefully.", cites=["E9"])
        assert "provenance" in ghost["failed"]
        handoff = _v(s, "Thanks, engineering will look.", kind="create_engineering_handoff", handoff={})
        assert "required_fields" in handoff["failed"]


def test_claim_support_keeps_methods_separate(db, tmp_path):
    seeded(db, tmp_path)
    with new_session() as s:
        r = _v(
            s,
            "Thanks for asking. SSO is included only in the Enterprise plan. Our office dog is called Biscuit.",
            cites=["E1"],
            evidence=PUBLIC,
        )
        by_text = {c["text"]: c for c in r["claims"]}
        assert by_text["Thanks for asking."]["verdict"] == "not_a_claim"
        assert by_text["SSO is included only in the Enterprise plan."]["method"] == "typed_entitlement"
        assert by_text["SSO is included only in the Enterprise plan."]["verdict"] == "supported"
        biscuit = by_text["Our office dog is called Biscuit."]
        assert (biscuit["verdict"], biscuit["method"]) == ("unavailable", "not_run")
        check = next(c for c in r["checks"] if c["name"] == "claim_support")
        assert check["status"] == "warn" and "not proof" in check["detail"]
        assert r["uncertain_claims"] == 1 and r["claim_verifier"] == {"kind": "not_run"}


def test_contradicted_number_fails_verification(db, tmp_path):
    seeded(db, tmp_path)
    evidence = {"E1": {**PUBLIC["E1"], "excerpt": "Business plans can export up to 25,000 rows per export."}}
    with new_session() as s:
        r = _v(s, "Your plan can export 50,000 rows at once.", cites=["E1"], evidence=evidence)
    assert "claim_support" in r["failed"]
    assert r["claims"][0]["method"] == "typed_number" and r["claims"][0]["evidence_ids"] == ["E1"]


def _record(db):
    rec = ActionRecord(
        organization_id="org_taskflow",
        customer_account_id="acct_northstar",
        idempotency_key="k1",
        proposal_id="p",
        review_id="r",
        run_id="x",
        ticket_id="t",
        action_kind="create_engineering_handoff",
        adapter="simulated",
        destination={},
        payload_hash="h",
        status="succeeded",
        receipt={},
    )
    return rec


def test_simulated_connector_outcomes_are_distinct(db, tmp_path):
    seeded(db, tmp_path)
    with new_session() as s:
        ok = actions.push_external(s, _record(s), actions.SimulatedIssueConnector("success"), "t")
        assert ok.status == "succeeded" and ok.receipt["external_id"] == "SIM-1"

        rejected = actions.push_external(s, _record(s), actions.SimulatedIssueConnector("reject"), "t")
        assert rejected.status == "failed"

        lost = actions.SimulatedIssueConnector("timeout_after_success")
        rec = actions.push_external(s, _record(s), lost, "t")
        assert rec.status == "unknown" and rec.receipt["needs_reconciliation"]
        rec = actions.push_external(s, rec, lost, "t")  # retry reconciles instead of recreating
        assert rec.status == "reconciled" and rec.receipt["external_id"] == "SIM-1"
        assert lost.create_calls == 1

        never = actions.SimulatedIssueConnector("timeout_before_create")
        rec = actions.push_external(s, _record(s), never, "t")
        assert rec.status == "unknown"
        rec = actions.reconcile(s, rec, never)
        assert rec.status == "unknown" and "operator decision" in rec.receipt["reconciliation"]
        assert never.create_calls == 1

        down = actions.SimulatedIssueConnector("unreachable")
        rec = actions.push_external(s, _record(s), actions.SimulatedIssueConnector("timeout_before_create"), "t")
        assert actions.reconcile(s, rec, down).status == "unknown"
        s.rollback()
