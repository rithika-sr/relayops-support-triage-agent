"""Operational/demo/test separation and server-derived provenance."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from relayops.api.main import app
from relayops.core.config import Settings
from relayops.core.instance import InstanceModeError, initialize, require_mode, validate_settings
from relayops.models import Organization, Ticket, TicketMessage
from relayops.services.seed import SeedRefused, seed
from tests.factories import HEADERS, build_world, client_for


def _set_mode(db, mode):
    db.execute(text("UPDATE instance_metadata SET data_mode = :m"), {"m": mode})
    db.commit()


def test_seed_refuses_operational_database(db, tmp_path):
    _set_mode(db, "operational")
    with pytest.raises(SeedRefused):
        seed(db, credentials_path=tmp_path / "c.json")
    assert db.query(Organization).count() == 0


def test_seed_refuses_when_configured_mode_differs(db, tmp_path, monkeypatch):
    _set_mode(db, "demo")  # configured mode is test in the suite
    with pytest.raises(SeedRefused):
        seed(db, credentials_path=tmp_path / "c.json")


def test_operational_mode_forbids_fixture_provider_and_dev_secrets():
    with pytest.raises(InstanceModeError):
        validate_settings(Settings(data_mode="operational", llm_provider="fixture", session_secret="x" * 40))
    with pytest.raises(InstanceModeError):
        validate_settings(Settings(data_mode="operational", llm_provider="ollama", session_secret="dev-only-change-me"))
    validate_settings(Settings(data_mode="operational", llm_provider="ollama", session_secret="s" * 48))


def test_initialize_refuses_to_label_demo_data_operational(db):
    db.execute(text("DELETE FROM instance_metadata"))
    db.add(Organization(id="org_demo", name="Demo", slug="demo", data_class="demo"))
    db.commit()
    with pytest.raises(InstanceModeError, match="demo-seeded"):
        initialize(db, Settings(data_mode="operational", session_secret="s" * 48))
    db.rollback()
    assert initialize(db, Settings(data_mode="demo", session_secret="s" * 48)) == "demo"
    db.commit()
    with pytest.raises(InstanceModeError, match="holds 'demo' data"):
        require_mode(db, Settings(data_mode="operational", llm_provider="ollama", session_secret="s" * 48))


def test_registration_and_tickets_carry_server_derived_provenance(db):
    c = TestClient(app)
    r = c.post(
        "/api/auth/register",
        headers=HEADERS,
        json={
            "name": "Owner",
            "email": "owner@new.test",
            "password": "a-long-enough-password",
            "organization_name": "New Co",
            "data_class": "operational",
        },
    )
    assert r.status_code == 200
    org = db.query(Organization).filter_by(slug="new-co").one()
    assert org.data_class == "test"  # the instance mode, never the request body


def test_ticket_channel_and_class_cannot_be_set_by_client(db):
    w = build_world(db)
    db.query(Organization).update({"data_class": "test"})
    db.commit()
    cust = client_for("cust1@a.test")
    r = cust.post(
        "/api/tickets",
        json={
            "subject": "Hello there",
            "body": "Something broke",
            "data_class": "operational",
            "source_kind": "connector",
            "source_system": "evil",
        },
    )
    t = db.get(Ticket, r.json()["ticket"]["id"])
    assert (t.data_class, t.source_kind, t.source_system) == ("test", "portal", None)
    assert t.received_at is not None
    staff = client_for("support@a.test")
    r = staff.post(
        "/api/tickets", json={"subject": "Phone call", "body": "Customer called in", "customer_account_id": w.acct_a1}
    )
    t2 = db.get(Ticket, r.json()["ticket"]["id"])
    assert t2.source_kind == "manual"
    msg = db.query(TicketMessage).filter_by(ticket_id=t2.id).one()
    assert (msg.data_class, msg.source_kind) == ("test", "manual")


def test_instance_endpoint_reports_mode_and_banner():
    r = TestClient(app).get("/api/instance").json()
    assert r["data_mode"] == "test" and "test" in r["banner"].lower()
