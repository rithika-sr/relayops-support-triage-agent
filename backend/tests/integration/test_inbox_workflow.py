"""Queues, sorting, assignment, bulk updates, saved views, and the Home summary."""

from __future__ import annotations

from datetime import timedelta

from relayops.core.clock import utcnow
from relayops.models import AuditEvent, Ticket
from tests.factories import build_world, client_for, principal


def _make(c, acct, subject, severity="normal"):
    r = c.post(
        "/api/tickets",
        json={
            "subject": subject,
            "body": "Details for " + subject,
            "customer_account_id": acct,
            "reported_severity": severity,
        },
    )
    return r.json()["ticket"]["id"]


def test_queues_sort_assignment_and_home(db):
    w = build_world(db)
    s = client_for("support@a.test")
    a = _make(s, w.acct_a1, "Low one", "low")
    b = _make(s, w.acct_a2, "Urgent one", "critical")
    c = _make(s, w.acct_a1, "Overdue one")
    db.query(Ticket).filter_by(id=c).update({"first_response_due_at": utcnow() - timedelta(hours=1)})
    db.commit()
    assert [t["id"] for t in s.get("/api/tickets?sort=priority").json()["items"]][0] == b
    assert [t["id"] for t in s.get("/api/tickets?queue=breached").json()["items"]] == [c]
    me = principal(db, "support@a.test")
    assert s.post(f"/api/tickets/{a}/assign", json={"assignee_user_id": me.user_id}).status_code == 200
    mine = s.get("/api/tickets?queue=open&assignee=me").json()
    assert [t["id"] for t in mine["items"]] == [a] and mine["items"][0]["assignee"]["name"] == "support"
    assert s.get("/api/tickets?assignee=none").json()["total"] == 2
    cust = principal(db, "cust1@a.test")
    assert s.post(f"/api/tickets/{a}/assign", json={"assignee_user_id": cust.user_id}).status_code == 422
    home = {q["key"]: q for q in s.get("/api/home").json()["queues"]}
    assert home["breached"]["count"] == 1 and home["mine"]["count"] == 1 and home["unassigned"]["count"] == 2
    assert home["breached"]["href"].startswith("/app/inbox?queue=breached")
    item = s.get("/api/tickets?q=Low one").json()["items"][0]
    assert item["preview"] == "Details for Low one"
    assert s.get("/api/tickets?sort=bogus").status_code == 422


def test_bulk_updates_check_each_ticket_and_audit(db):
    w = build_world(db)
    s = client_for("support@a.test")
    ids = [_make(s, w.acct_a1, f"Bulk {i}") for i in range(3)]
    other = _make(client_for("support@b.test"), w.acct_b1, "Other org")
    r = s.post("/api/tickets/bulk", json={"ticket_ids": [*ids, other], "changes": {"priority": "high"}}).json()
    assert r["updated"] == 3 and r["results"][other].startswith("skipped")
    assert db.get(Ticket, other).priority == "normal"
    assert db.query(AuditEvent).filter_by(action="ticket.updated").count() == 3
    bad = s.post("/api/tickets/bulk", json={"ticket_ids": ids, "changes": {"customer_reply": "hi"}})
    assert bad.status_code == 422
    assert (
        client_for("cust1@a.test")
        .post("/api/tickets/bulk", json={"ticket_ids": ids, "changes": {"priority": "low"}})
        .status_code
        == 403
    )


def test_saved_views_are_per_user(db):
    build_world(db)
    s = client_for("support@a.test")
    v = s.post("/api/views", json={"name": "Overdue", "query": "?queue=breached&sort=due"}).json()
    assert v["query"] == "queue=breached&sort=due"
    assert [x["name"] for x in s.get("/api/views").json()] == ["Overdue"]
    assert client_for("admin@a.test").get("/api/views").json() == []
    assert client_for("admin@a.test").delete(f"/api/views/{v['id']}").status_code == 404
    assert s.post("/api/views", json={"name": "x", "query": "https://evil"}).status_code == 422
    assert s.delete(f"/api/views/{v['id']}").status_code == 204
