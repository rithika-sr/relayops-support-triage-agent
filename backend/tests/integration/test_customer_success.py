"""Events schema and dedupe, self-service Help, onboarding, retention, opportunities, and experiments."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from relayops.core.clock import utcnow
from relayops.core.db import new_session
from relayops.domain import events as schema
from relayops.models import KnowledgeDocument, ProductEvent
from relayops.services import events, experiments
from tests.agent_helpers import ADMIN, CUSTOMER, SUPPORT, client, seeded

ORG, ACCT = "org_taskflow", "acct_northstar"


@pytest.fixture
def w(db, tmp_path):
    creds = seeded(db, tmp_path)
    return {"cust": client(CUSTOMER, creds), "support": client(SUPPORT, creds), "admin": client(ADMIN, creds)}


def _names(account=ACCT):
    with new_session() as s:
        return [
            e.name
            for e in s.execute(
                select(ProductEvent)
                .where(ProductEvent.customer_account_id == account)
                .order_by(ProductEvent.occurred_at)
            ).scalars()
        ]


def _emit(name, props, *, account=ACCT, ago=timedelta(0), event_id=None, data_class=None):
    with new_session() as s:
        ok = events.record(
            s,
            organization_id=ORG,
            name=name,
            properties=props,
            customer_account_id=account,
            occurred_at=utcnow() - ago,
            event_id=event_id,
            data_class=data_class,
        )
        s.commit()
        return ok


@pytest.mark.parametrize(
    ("name", "props", "msg"),
    [
        ("page.viewed", {}, "unknown event"),
        ("help.searched", {"query": "x"}, "missing results"),
        ("help.searched", {"query": "x", "results": True}, "must be int"),
        ("article.feedback", {"document_id": "d", "helpful": "yes"}, "must be bool"),
        ("user.signed_in", {"email": "a@b"}, "unknown properties"),
    ],
)
def test_schema_rejects_unknown_names_fields_and_types(name, props, msg):
    with pytest.raises(schema.EventInvalid, match=msg):
        schema.validate(name, props)
    with pytest.raises(schema.EventInvalid, match="schema version"):
        schema.validate("user.signed_in", {}, version=2)


def test_dedupe_and_import(w):
    assert _emit("user.signed_in", {}, event_id="e1") and not _emit("user.signed_in", {}, event_id="e1")
    items = [
        {
            "event_id": "x1",
            "name": "help.searched",
            "occurred_at": (utcnow() - timedelta(days=2)).isoformat(),
            "customer_account_id": ACCT,
            "properties": {"query": "sso", "results": 0},
        }
    ]
    admin = w["admin"]
    assert w["support"].post("/api/events/import", json={"items": items}).status_code == 403
    dry = admin.post("/api/events/import", json={"items": items}).json()
    assert dry["accepted"] == 1 and not dry["committed"]
    bad = admin.post(
        "/api/events/import",
        json={
            "dry_run": False,
            "items": items
            + [
                {**items[0], "event_id": "x2", "occurred_at": (utcnow() + timedelta(days=1)).isoformat()},
                {**items[0], "event_id": "x3", "customer_account_id": "acct_not_here"},
            ],
        },
    ).json()
    assert not bad["committed"] and [e["row"] for e in bad["errors"]] == [1, 2]
    ok = admin.post("/api/events/import", json={"dry_run": False, "items": items}).json()
    again = admin.post("/api/events/import", json={"dry_run": False, "items": items}).json()
    assert ok["accepted"] == 1 and again["duplicates"] == 1


def test_self_service_help_journey(w):
    cust = w["cust"]
    assert w["support"].get("/api/portal/help/search?q=export").status_code == 403
    res = cust.get("/api/portal/help/search?q=export rows limit").json()
    assert res["results"]
    with new_session() as s:
        internal = s.execute(
            select(KnowledgeDocument.id).where(
                KnowledgeDocument.organization_id == ORG, KnowledgeDocument.visibility == "internal"
            )
        ).scalar()
        vis = dict(s.execute(select(KnowledgeDocument.id, KnowledgeDocument.visibility)).all())
    assert all(vis[r["document_id"]] == "public" for r in res["results"])
    assert cust.get(f"/api/portal/help/articles/{internal}").status_code == 404
    doc = res["results"][0]["document_id"]
    art = cust.get(f"/api/portal/help/articles/{doc}").json()
    assert art["content"] and art["title"]
    assert cust.post(f"/api/portal/help/articles/{doc}/feedback", json={"helpful": False}).json() == {"recorded": True}
    t = cust.post(
        "/api/portal/help/contact",
        json={
            "subject": "Export still fails",
            "body": "The article did not help.",
            "document_id": doc,
            "query": "export rows limit",
        },
    )
    assert t.status_code == 201
    names = _names()
    assert {
        "user.signed_in",
        "help.searched",
        "article.viewed",
        "article.feedback",
        "help.escalated",
        "ticket.created",
    } <= set(names)


def test_onboarding_is_computed_from_records(w):
    ob = w["cust"].get("/api/portal/onboarding").json()
    steps = {s["id"]: s for s in ob["steps"]}
    assert steps["signed_in"]["done"] and steps["signed_in"]["at"]
    assert not steps["first_ticket"]["done"] and not steps["first_reply"]["done"]
    w["cust"].post("/api/tickets", json={"subject": "How do I export?", "body": "Where is the export button?"})
    steps = {s["id"]: s for s in w["support"].get(f"/api/success/accounts/{ACCT}/onboarding").json()["steps"]}
    assert steps["first_ticket"]["done"] and not steps["first_reply"]["done"]


def test_retention_marks_unreached_weeks_pending_not_zero(w):
    other = "acct_acme"
    _emit("user.signed_in", {}, account=other, ago=timedelta(days=22))  # cohort three weeks ago
    _emit("user.signed_in", {}, account=other, ago=timedelta(days=15))  # active in week 1, not week 2
    ret = w["support"].get("/api/success/retention?weeks=5").json()
    row = next(r for r in ret["cohorts"] if r["accounts"] >= 1 and r["weeks"][0]["status"] == "measured")
    cells = {c["week"]: c for c in row["weeks"]}
    assert cells[1]["status"] == "measured" and cells[1]["active"] >= 1
    assert cells[2]["status"] == "measured"
    assert cells[3]["status"] == "pending" and cells[4]["status"] == "pending"  # not yet reachable: not 0%
    # Today's cohort (the customer signed in during setup) has nothing measured yet.
    today = [r for r in ret["cohorts"] if all(c["status"] == "pending" for c in r["weeks"])]
    assert today


def test_opportunities_follow_documented_rules_and_exclude_other_classes(w):
    assert w["support"].get("/api/success/opportunities").json()["cards"] == []
    with new_session() as s:
        doc = s.execute(
            select(KnowledgeDocument.id).where(
                KnowledgeDocument.organization_id == ORG, KnowledgeDocument.visibility == "public"
            )
        ).scalar()
    for i in range(3):
        with new_session() as s:
            events.record(
                s,
                organization_id=ORG,
                name="article.feedback",
                customer_account_id=ACCT,
                actor_user_id=None,
                properties={"document_id": doc, "helpful": False},
                event_id=f"fb{i}",
            )
            s.commit()
        _emit("help.searched", {"query": "Okta SCIM?", "results": 0}, event_id=f"zs{i}")
    for i in range(5):  # demo-class events never count in a test instance
        _emit("help.searched", {"query": "demo gap", "results": 0}, event_id=f"demo{i}", data_class="demo")
    cards = w["support"].get("/api/success/opportunities").json()["cards"]
    kinds = {c["kind"]: c for c in cards}
    assert "knowledge_gap" in kinds and kinds["knowledge_gap"]["title"] == "Write Help for “okta scim”"
    assert all("demo gap" not in c["title"] for c in cards)
    # Three votes with no reader identity collapse to one latest vote: below the rule's minimum.
    assert "improve_article" not in kinds


def test_experiment_lifecycle_and_honest_results(w):
    admin, cust = w["admin"], w["cust"]
    bad = admin.post("/api/experiments", json={"key": "x", "hypothesis": "short", "variants": ["lexical"]})
    assert bad.status_code == 422
    body = {
        "key": "help-ranking",
        "variants": ["lexical", "rrf"],
        "min_accounts_per_variant": 10,
        "hypothesis": "Hybrid ranking lowers how often searching accounts contact support from Help.",
    }
    exp = admin.post("/api/experiments", json=body).json()
    assert w["support"].post(f"/api/experiments/{exp['id']}/start").status_code == 403
    assert admin.post(f"/api/experiments/{exp['id']}/start").json()["status"] == "running"
    r1 = cust.get("/api/portal/help/search?q=export").json()
    r2 = cust.get("/api/portal/help/search?q=webhooks").json()
    assert r1["ranking"] == r2["ranking"] == experiments.assign("help-ranking", ACCT, ["lexical", "rrf"])
    assert _names().count("experiment.exposed") == 1
    listed = w["support"].get("/api/experiments").json()[0]
    assert listed["results"]["status"] == "insufficient_sample" and "difference" not in listed["results"]
    # Measured only once every variant reaches the pre-registered minimum (test accounts created here).
    from relayops.models import CustomerAccount

    with new_session() as ses:
        for i in range(24):
            ses.add(
                CustomerAccount(
                    id=f"acct_exp{i}", organization_id=ORG, name=f"Exp {i}", plan="team", product_version="2.5"
                )
            )
        ses.commit()
    for i in range(24):  # hash split: 11 lexical, 13 rrf
        variant = experiments.assign("help-ranking", f"acct_exp{i}", ["lexical", "rrf"])
        _emit(
            "experiment.exposed",
            {"experiment": "help-ranking", "variant": variant},
            account=f"acct_exp{i}",
            event_id=f"exp-x{i}",
        )
        if i % 4 == 0:
            _emit("help.escalated", {"ticket_id": f"t{i}"}, account=f"acct_exp{i}", event_id=f"exp-esc{i}")
    res = w["support"].get("/api/experiments").json()[0]["results"]
    assert res["status"] == "measured" and min(v["accounts"] for v in res["variants"].values()) >= 10
    assert res["difference"]["of"] == "rrf minus lexical" and len(res["difference"]["ci95"]) == 2
    assert admin.post(f"/api/experiments/{exp['id']}/stop").json()["status"] == "stopped"
    assert admin.post(f"/api/experiments/{exp['id']}/start").status_code == 409  # no restart after stopping
