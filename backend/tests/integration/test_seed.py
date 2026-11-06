from __future__ import annotations

import json
import stat

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from relayops.api.main import app
from relayops.core.db import new_session
from relayops.models import ErrorAggregate, KnowledgeDocument, Ticket, User
from relayops.services.seed import seed
from tests.factories import HEADERS


def _counts(db):
    return tuple(db.execute(select(func.count(m.id))).scalar_one() for m in (Ticket, KnowledgeDocument, ErrorAggregate))


def test_seed_is_idempotent_and_credentials_log_in(db, tmp_path):
    creds_path = tmp_path / "demo-credentials.json"
    first = seed(db, credentials_path=creds_path)
    db.commit()
    before = _counts(db)
    saved = creds_path.read_text()
    assert stat.S_IMODE(creds_path.stat().st_mode) == 0o600
    with new_session() as db2:
        seed(db2, credentials_path=creds_path)
        db2.commit()
        assert _counts(db2) == before
    assert creds_path.read_text() == saved
    assert first["counts"]["documents"] >= 50 and first["counts"]["tickets"] >= 120

    creds = json.loads(saved)["accounts"]
    for email, role, home in [
        ("admin@relayops.local", "admin", "/app"),
        ("support@relayops.local", "support", "/app"),
        ("customer@northstar.local", "customer", "/portal"),
    ]:
        assert creds[email]["role"] == role
        hashed = db.execute(select(User.password_hash).where(User.email == email)).scalar_one()
        assert creds[email]["password"] not in hashed
        c = TestClient(app)
        r = c.post("/api/auth/login", json={"email": email, "password": creds[email]["password"]}, headers=HEADERS)
        assert r.status_code == 200 and r.json()["redirect_to"] == home


def test_seeded_customer_sees_only_northstar(db, tmp_path):
    creds_path = tmp_path / "c.json"
    seed(db, credentials_path=creds_path)
    db.commit()
    pw = json.loads(creds_path.read_text())["accounts"]["customer@northstar.local"]["password"]
    c = TestClient(app)
    c.post("/api/auth/login", json={"email": "customer@northstar.local", "password": pw}, headers=HEADERS)
    assert c.get("/api/tickets").json()["total"] == 0  # historical tickets are not part of the portal
    slugs = {d["slug"] for d in c.get("/api/knowledge").json()}
    assert "northstar-export-schedule" in slugs
    assert not {"acme-escalation-contacts", "exports-triage-runbook", "quill-plan-policy"} & slugs
    assert not any(s.startswith("case-") for s in slugs)
