"""Imports and signed inbound webhooks: scope, signatures, replay, idempotency, and provenance."""

from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient

from relayops.api.main import app
from relayops.models import Connection, IngestionReceipt, Ticket
from relayops.services.ingestion import sign
from tests.factories import build_world, client_for

CSV = (
    "external_id,account,subject,body,severity,component,error_code\n"
    "r1,A One,Export broken,Export fails with EXPORT_500,normal,exports,EXPORT_500\n"
    "r2,A Two,SSO question,Can we enable SSO for staff?,low,sso,\n"
    "r2,A Two,SSO question,Can we enable SSO for staff?,low,sso,\n"
    "r3,B One,Cross tenant,Should never be accepted here,normal,,\n"
    "r4,A One,x,too short,normal,,\n"
)


def _upload(c, path, data, **form):
    return c.post(path, files={"file": ("tickets.csv", data, "text/csv")}, data=form)


def test_import_preview_writes_nothing_and_commit_is_idempotent(db):
    build_world(db)
    staff = client_for("support@a.test")
    pv = _upload(staff, "/api/imports/preview", CSV.encode()).json()
    assert pv["counts"] == {"ok": 2, "duplicate": 1, "error": 2}
    assert db.query(Ticket).count() == 0
    bad = [r for r in pv["rows"] if r["status"] == "error"]
    assert "unknown customer account 'B One'" in bad[0]["errors"][0]  # other org's account is not resolvable
    stale = _upload(staff, "/api/imports", CSV.encode() + b"\n", expected_sha256=pv["content_sha256"])
    assert stale.status_code == 422
    r = _upload(staff, "/api/imports", CSV.encode(), expected_sha256=pv["content_sha256"])
    assert r.status_code == 201 and r.json()["created_count"] == 2
    t = db.query(Ticket).filter_by(external_event_id="import:r1").one()
    assert (t.source_kind, t.import_batch_id) == ("import", r.json()["id"])
    again = _upload(staff, "/api/imports/preview", CSV.encode()).json()
    assert again["counts"]["duplicate"] == 3 and again["counts"]["ok"] == 0
    assert (
        client_for("cust1@a.test").post("/api/imports/preview", files={"file": ("t.csv", b"x", "text/csv")}).status_code
        == 403
    )


def test_import_rejects_wrong_types_and_oversize(db):
    build_world(db)
    staff = client_for("support@a.test")
    assert staff.post("/api/imports/preview", files={"file": ("t.txt", b"a", "text/plain")}).status_code == 422
    big = b"external_id,account,subject,body\n" + b"x" * 1_000_100
    assert staff.post("/api/imports/preview", files={"file": ("t.csv", big, "text/csv")}).status_code == 422
    js = json.dumps(
        [
            {
                "external_id": "j1",
                "account": "A One",
                "subject": "JSON row",
                "body": "From a JSON file",
                "organization_id": "org_b",
            }
        ]
    ).encode()
    pv = staff.post("/api/imports/preview", files={"file": ("t.json", js, "application/json")}).json()
    assert pv["counts"]["error"] == 1  # unknown fields such as organization_id are refused


def _connection(db, admin):
    r = admin.post("/api/integrations/webhooks", json={"name": "helpdesk", "account_map": {"cust-001": "acct_a1"}})
    assert r.status_code == 201, r.text
    return r.json()["connection"]["id"], r.json()["signing_secret"]


def _post(c, cid, secret, payload, ts=None, raw=None):
    body = raw if raw is not None else json.dumps(payload).encode()
    ts = str(ts or int(time.time()))
    return c.post(
        f"/api/ingest/webhooks/{cid}",
        content=body,
        headers={
            "x-relayops-timestamp": ts,
            "x-relayops-signature": sign(secret, ts, body),
            "content-type": "application/json",
        },
    )


EVENT = {
    "event_id": "evt-1",
    "account_ref": "cust-001",
    "subject": "Webhook ticket",
    "body": "Arrived from helpdesk",
    "error_code": "EXPORT_500",
    "occurred_at": "2026-11-06T10:00:00Z",
}


def test_signed_webhook_creates_one_ticket_with_connector_provenance(db):
    build_world(db)
    admin = client_for("admin@a.test")
    cid, secret = _connection(db, admin)
    anon = TestClient(app)
    r = _post(anon, cid, secret, EVENT)
    assert r.status_code == 202, r.text
    t = db.get(Ticket, r.json()["ticket_id"])
    assert (t.source_kind, t.source_connection_id, t.customer_account_id, t.created_by_user_id) == (
        "connector",
        cid,
        "acct_a1",
        None,
    )
    assert t.source_event_at.isoformat().startswith("2026-11-06T10:00")
    replay = _post(anon, cid, secret, EVENT)
    assert replay.status_code == 202 and replay.json()["ticket_id"] == t.id
    assert db.query(Ticket).count() == 1
    conflict = _post(anon, cid, secret, {**EVENT, "subject": "Changed"})
    assert conflict.status_code == 409
    db.expire_all()
    assert db.get(Connection, cid).status == "healthy"
    receipts = admin.get(f"/api/integrations/{cid}/receipts").json()
    assert [x["status"] for x in receipts] == ["accepted"]


def test_webhook_rejects_tampering_replay_scope_and_size(db):
    build_world(db)
    admin = client_for("admin@a.test")
    cid, secret = _connection(db, admin)
    anon = TestClient(app)
    body = json.dumps(EVENT).encode()
    ts = str(int(time.time()))
    tampered = anon.post(
        f"/api/ingest/webhooks/{cid}",
        content=body + b" ",
        headers={"x-relayops-timestamp": ts, "x-relayops-signature": sign(secret, ts, body)},
    )
    assert tampered.status_code == 401
    assert _post(anon, cid, secret, EVENT, ts=int(time.time()) - 3600).status_code == 401
    assert _post(anon, cid, "whsec_wrong", EVENT).status_code == 401
    assert anon.post(f"/api/ingest/webhooks/{cid}", content=body).status_code == 401
    unmapped = _post(anon, cid, secret, {**EVENT, "event_id": "evt-2", "account_ref": "acct_b1"})
    assert unmapped.status_code == 422 and "not mapped" in unmapped.json()["reason"]
    injected = _post(anon, cid, secret, {**EVENT, "event_id": "evt-3", "customer_account_id": "acct_b1"})
    assert injected.status_code == 422
    attach = _post(anon, cid, secret, {**EVENT, "event_id": "evt-4", "attachments": ["http://x/y"]})
    assert attach.status_code == 422
    assert _post(anon, cid, secret, {}, raw=b"x" * 70_000).status_code == 413
    assert db.query(Ticket).count() == 0
    db.expire_all()
    c = db.get(Connection, cid)
    assert c.last_error and c.status in ("configured", "degraded")
    assert {r.status for r in db.query(IngestionReceipt)} == {"rejected"}


def test_connections_are_admin_only_and_org_scoped(db):
    build_world(db)
    assert client_for("support@a.test").get("/api/integrations").status_code == 403
    other = client_for("admin@b.test")
    r = other.post("/api/integrations/webhooks", json={"name": "x", "account_map": {"c": "acct_a1"}})
    assert r.status_code == 404  # cannot map another organization's account
    cid, _ = _connection(db, client_for("admin@a.test"))
    assert other.get(f"/api/integrations/{cid}/receipts").status_code == 404
    assert client_for("admin@a.test").post(f"/api/integrations/{cid}/disable").json()["status"] == "disconnected"
    assert _post(TestClient(app), cid, "irrelevant", EVENT).status_code == 403
