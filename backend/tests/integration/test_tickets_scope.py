from __future__ import annotations

from sqlalchemy import select

from relayops.models import Ticket
from tests.factories import build_world, client_for


def _ticket(c, **kw):
    body = {"subject": "Export broken", "body": "CSV export fails with EXPORT_500.", "component": "exports", **kw}
    r = c.post("/api/tickets", json=body)
    assert r.status_code == 201, r.text
    return r.json()["ticket"]


def test_customer_ticket_is_forced_to_own_account_with_policy_target(db):
    w = build_world(db)
    cust = client_for("cust1@a.test")
    t = _ticket(cust, customer_account_id=w.acct_a2, reported_severity="high")
    row = db.get(Ticket, t["id"])
    assert row.customer_account_id == w.acct_a1
    # business plan, high priority => 4h elapsed target
    assert (row.first_response_due_at - row.created_at).total_seconds() == 4 * 3600
    assert row.target_policy["basis"] == "24/7 elapsed hours"
    assert "revision" not in t and "target" not in t  # staff-only fields not projected to customers


def test_customers_cannot_read_other_accounts_or_internal_notes(db):
    w = build_world(db)
    c1, c2 = client_for("cust1@a.test"), client_for("cust2@a.test")
    t = _ticket(c1)
    support = client_for("support@a.test")
    assert (
        support.post(
            f"/api/tickets/{t['id']}/messages", json={"body": "internal: likely ENG-1", "visibility": "internal"}
        ).status_code
        == 201
    )
    assert c2.get(f"/api/tickets/{t['id']}").status_code == 404
    assert c2.post(f"/api/tickets/{t['id']}/messages", json={"body": "hi"}).status_code == 404
    assert c2.get("/api/tickets").json()["total"] == 0
    detail = c1.get(f"/api/tickets/{t['id']}").json()
    assert [m["visibility"] for m in detail["messages"]] == ["customer"]
    assert "runs" not in detail and "account" not in detail
    assert w


def test_staff_cannot_cross_organizations_by_id(db):
    build_world(db)
    t = _ticket(client_for("cust1@a.test"))
    other = client_for("support@b.test")
    assert other.get(f"/api/tickets/{t['id']}").status_code == 404
    assert other.patch(f"/api/tickets/{t['id']}", json={"status": "closed"}).status_code == 404
    assert other.get("/api/tickets").json()["total"] == 0
    assert other.get("/api/overview").json()["open_tickets"] == 0
    csv = other.get("/api/tickets/export.csv").text
    assert "Export broken" not in csv


def test_staff_must_choose_an_account_in_their_org(db):
    w = build_world(db)
    s = client_for("support@a.test")
    assert s.post("/api/tickets", json={"subject": "abc", "body": "abcdef"}).status_code == 422
    r = s.post("/api/tickets", json={"subject": "abc", "body": "abcdef", "customer_account_id": w.acct_b1})
    assert r.status_code == 404


def test_customer_cannot_post_internal_note_or_use_staff_endpoints(db):
    build_world(db)
    c = client_for("cust1@a.test")
    t = _ticket(c)
    m = c.post(f"/api/tickets/{t['id']}/messages", json={"body": "secret?", "visibility": "internal"})
    assert m.json()["visibility"] == "customer"
    assert c.patch(f"/api/tickets/{t['id']}", json={"status": "resolved"}).status_code == 403
    assert c.get("/api/overview").status_code == 403
    assert c.get("/api/tickets/export.csv").status_code == 403


def test_customer_message_bumps_revision_and_staff_cannot_bypass_review(db):
    build_world(db)
    c = client_for("cust1@a.test")
    t = _ticket(c)
    before = db.get(Ticket, t["id"]).revision
    c.post(f"/api/tickets/{t['id']}/messages", json={"body": "Also it fails on 2.5 now."})
    db.expire_all()
    assert db.get(Ticket, t["id"]).revision == before + 1
    s = client_for("support@a.test")
    r = s.post(f"/api/tickets/{t['id']}/messages", json={"body": "direct reply", "visibility": "customer"})
    assert r.status_code == 422


def test_replayed_intake_with_same_external_event_returns_original(db):
    build_world(db)
    c = client_for("cust1@a.test")
    a = c.post("/api/tickets", json={"subject": "Dup", "body": "same event body", "external_event_id": "evt-1"})
    b = c.post("/api/tickets", json={"subject": "Dup", "body": "same event body", "external_event_id": "evt-1"})
    assert a.json()["created"] is True and b.json()["created"] is False
    assert a.json()["ticket"]["id"] == b.json()["ticket"]["id"]
    assert len(db.execute(select(Ticket)).scalars().all()) == 1


def test_security_language_creates_restricted_ticket(db):
    build_world(db)
    t = _ticket(
        client_for("cust1@a.test"),
        subject="Possible security vulnerability",
        body="I think there is an XSS vulnerability in comments.",
    )
    row = db.get(Ticket, t["id"])
    assert row.restricted and row.priority in ("high", "urgent")


def test_inbox_filters_and_pagination(db):
    w = build_world(db)
    s = client_for("support@a.test")
    for i in range(7):
        s.post(
            "/api/tickets",
            json={
                "subject": f"Ticket {i}",
                "body": "body text",
                "customer_account_id": w.acct_a1 if i % 2 else w.acct_a2,
                "component": "api" if i < 3 else "billing",
            },
        )
    page = s.get("/api/tickets?page_size=3&page=3").json()
    assert page["total"] == 7 and len(page["items"]) == 1
    assert s.get(f"/api/tickets?account_id={w.acct_a1}").json()["total"] == 3
    assert s.get("/api/tickets?component=api").json()["total"] == 3
    assert s.get("/api/tickets?q=Ticket 4").json()["total"] == 1
    ov = s.get("/api/overview").json()
    assert ov["open_tickets"] == 7 and sum(ov["open_by_component"].values()) == 7


def test_new_registered_org_sees_no_existing_tenant_data(db):
    from fastapi.testclient import TestClient

    from relayops.api.main import app
    from tests.factories import HEADERS

    build_world(db)
    _ticket(client_for("cust1@a.test"))
    c = TestClient(app)
    c.post(
        "/api/auth/register",
        headers=HEADERS,
        json={"name": "M", "email": "m@x.test", "password": "a-very-long-password", "organization_name": "Org A"},
    )
    assert c.get("/api/accounts").json() == []
    assert c.get("/api/tickets").json()["total"] == 0


def test_analytics_count_only_the_instance_data_class(db):
    from sqlalchemy import update

    from relayops.core.db import new_session
    from relayops.models import Ticket

    w = build_world(db)
    s = client_for("support@a.test")
    for i in range(3):
        r = s.post(
            "/api/tickets", json={"subject": f"Ticket {i}", "body": "body text", "customer_account_id": w.acct_a1}
        )
        assert r.status_code == 201, r.text
    with new_session() as ses:
        ids = [t.id for t in ses.query(Ticket).filter(Ticket.organization_id == w.org_a).order_by(Ticket.id)]
        ses.execute(update(Ticket).where(Ticket.id == ids[0]).values(data_class="demo"))
        ses.execute(update(Ticket).where(Ticket.id == ids[1]).values(data_class="unknown"))
        ses.commit()
    ov = s.get("/api/overview").json()
    assert ov["data_classes_included"] == ["test"]
    assert ov["open_tickets"] == 1 and ov["excluded_tickets_by_class"] == {"demo": 1, "unknown": 1}


def test_fresh_organization_can_add_an_account_and_take_a_real_ticket(db):
    from fastapi.testclient import TestClient

    from relayops.api.main import app
    from tests.factories import HEADERS

    c = TestClient(app)
    r = c.post(
        "/api/auth/register",
        headers=HEADERS,
        json={
            "name": "Ada",
            "email": "ada@new.test",
            "password": "a-very-long-password",
            "organization_name": "New Co",
        },
    )
    assert r.status_code in (200, 201), r.text
    c.headers.update({"x-csrf-token": c.cookies.get("relayops_csrf") or "", "origin": "http://localhost:3020"})
    assert c.get("/api/overview").json()["open_tickets"] == 0  # starts empty: nothing seeded
    bad = c.post("/api/settings/accounts", json={"name": "Acme", "plan": "platinum", "product_version": "2.5"})
    assert bad.status_code == 422
    acct = c.post("/api/settings/accounts", json={"name": "Acme", "plan": "team", "product_version": "2.5"})
    assert acct.status_code == 201, acct.text
    assert (
        c.post("/api/settings/accounts", json={"name": "Acme", "plan": "team", "product_version": "2.5"}).status_code
        == 422
    )
    t = c.post(
        "/api/tickets",
        json={
            "subject": "Exports fail",
            "body": "CSV export returns an error.",
            "customer_account_id": acct.json()["id"],
        },
    )
    assert t.status_code == 201
    detail = c.get(f"/api/tickets/{t.json()['ticket']['id']}").json()["ticket"]
    assert detail["data_class"] == "test" and detail["source_kind"] == "manual"  # the instance's class, set by server
    assert c.get("/api/overview").json()["open_tickets"] == 1
