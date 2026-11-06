"""Read-tool contracts: typed arguments, trusted scope, observation states, and isolation."""

from __future__ import annotations

from relayops.core.clock import utcnow
from relayops.core.db import new_session
from relayops.domain.playbooks import READ_TOOLS
from relayops.tools.registry import TOOLS, TrustedContext, dispatch, tool_specs
from tests.agent_helpers import seeded


def _ctx(**kw):
    base = dict(
        run_id="run_x",
        organization_id="org_taskflow",
        customer_account_id="acct_northstar",
        ticket_id="tkt_x",
        as_of=utcnow(),
        product_version="2.4",
        component="exports",
        allowed_tools=READ_TOOLS,
        retrieval_mode="lexical",
        error_signature="EXPORT_500",
    )
    return TrustedContext(**{**base, **kw})


def test_registry_exposes_exactly_the_six_read_tools():
    assert (
        set(TOOLS)
        == set(READ_TOOLS)
        == {
            "search_knowledge",
            "find_similar_cases",
            "search_engineering_issues",
            "get_incident_snapshot",
            "get_recent_deployments",
            "get_error_aggregates",
        }
    )
    for spec in tool_specs(READ_TOOLS):
        assert not {"organization_id", "customer_account_id", "role", "tenant"} & set(spec["args"])


def test_model_cannot_inject_scope_or_unknown_tools(db, tmp_path):
    seeded(db, tmp_path)
    with new_session() as s:
        bad = dispatch(s, _ctx(), "search_knowledge", {"query": "exports", "organization_id": "org_quillstack"})
        assert bad.status == "failed" and "Invalid arguments" in bad.summary
        assert dispatch(s, _ctx(), "run_sql", {"q": "select 1"}).status == "failed"
        limited = dispatch(s, _ctx(allowed_tools=("search_knowledge",)), "get_error_aggregates", {})
        assert limited.status == "unauthorized"
        too_far = dispatch(s, _ctx(), "get_recent_deployments", {"lookback_hours": 10_000})
        assert too_far.status == "failed"


def test_knowledge_tools_never_cross_org_or_account(db, tmp_path):
    seeded(db, tmp_path)
    with new_session() as s:
        for q in (
            "EXPORT_500 export failures ledger plugin QUILLSTACK-PRIVATE",
            "SSO included every plan",
            "Acme escalation contract webhooks business critical",
        ):
            for tool in ("search_knowledge", "find_similar_cases"):
                obs = dispatch(s, _ctx(), tool, {"query": q})
                text = " ".join(e.excerpt + e.title for e in obs.evidence)
                assert "QUILLSTACK" not in text and "ACME-ENT-2291" not in text, (tool, q)
        issues = dispatch(s, _ctx(), "search_engineering_issues", {"query": "EXPORT_500"})
        assert all(not e.title.startswith("QS-") for e in issues.evidence)
        assert any(e.meta["key"] == "ENG-101" and e.meta["match"]["version"] for e in issues.evidence)
        acme = dispatch(
            s, _ctx(customer_account_id="acct_acme"), "search_knowledge", {"query": "Acme escalation contacts webhooks"}
        )
        assert any("ACME-ENT-2291" in e.excerpt for e in acme.evidence)


def test_diagnostics_report_counts_and_distinct_states(db, tmp_path):
    seeded(db, tmp_path)
    with new_session() as s:
        agg = dispatch(
            s,
            _ctx(customer_account_id="acct_acme", component="webhooks"),
            "get_error_aggregates",
            {"error_signature": "WEBHOOK_SIG_MISMATCH", "lookback_hours": 96},
        )
        assert agg.status == "ok"
        series = agg.evidence[0].meta
        assert series["distinct_accounts"] == 2 and series["this_account_errors"] > 0
        empty = dispatch(s, _ctx(), "get_error_aggregates", {"error_signature": "NO_SUCH_ERROR"})
        assert empty.status == "empty"
        deps = dispatch(s, _ctx(component="webhooks"), "get_recent_deployments", {"component": "webhooks"})
        assert deps.status == "ok" and "correlation" in deps.summary
        old = dispatch(s, _ctx(as_of=utcnow().replace(year=2030)), "get_error_aggregates", {})
        assert old.status in ("stale", "empty")
        inc = dispatch(s, _ctx(component="sso"), "get_incident_snapshot", {"component": "sso"})
        assert inc.evidence and inc.evidence[0].visibility == "internal"  # not public: never customer evidence
