from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from relayops.api.main import app
from relayops.core.clock import utcnow
from relayops.core.security import token_digest
from relayops.models import AuthSession, Membership, User
from tests.factories import HEADERS, PASSWORD, build_world, login


def test_login_sets_httponly_session_and_hashes_token(db):
    build_world(db)
    c = TestClient(app)
    r = c.post(
        "/api/auth/login", json={"email": "Support@A.test", "password": PASSWORD, "next": "/app/inbox"}, headers=HEADERS
    )
    assert r.status_code == 200
    assert r.json()["redirect_to"] == "/app/inbox"
    cookie = r.headers["set-cookie"]
    assert "relayops_session=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    token = c.cookies.get("relayops_session")
    rows = db.execute(select(AuthSession)).scalars().all()
    assert len(rows) == 1
    assert rows[0].token_hash == token_digest(token) and token not in rows[0].token_hash
    pw = db.execute(select(User.password_hash).where(User.email == "support@a.test")).scalar_one()
    assert pw.startswith("$argon2") and PASSWORD not in pw


def test_wrong_password_and_unknown_email_get_same_error(db):
    build_world(db)
    c = TestClient(app)
    a = c.post("/api/auth/login", json={"email": "support@a.test", "password": "nope-nope-nope"}, headers=HEADERS)
    b = c.post("/api/auth/login", json={"email": "ghost@a.test", "password": "nope-nope-nope"}, headers=HEADERS)
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_login_is_throttled_after_repeated_failures(db):
    build_world(db)
    c = TestClient(app)
    for _ in range(5):
        assert (
            c.post(
                "/api/auth/login", json={"email": "cust1@a.test", "password": "bad-password-x"}, headers=HEADERS
            ).status_code
            == 401
        )
    r = c.post("/api/auth/login", json={"email": "cust1@a.test", "password": PASSWORD}, headers=HEADERS)
    assert r.status_code == 429 and "Retry-After" in r.headers


def test_login_requires_same_origin_guard_header(db):
    build_world(db)
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"email": "support@a.test", "password": PASSWORD}).status_code == 403
    r = c.post(
        "/api/auth/login",
        json={"email": "support@a.test", "password": PASSWORD},
        headers={"x-requested-with": "relayops", "origin": "https://evil.example"},
    )
    assert r.status_code == 403


def test_logout_revokes_session_server_side(db):
    build_world(db)
    c = login(TestClient(app), "support@a.test")
    token = c.cookies.get("relayops_session")
    assert c.get("/api/auth/me").status_code == 200
    assert c.post("/api/auth/logout").status_code == 200
    replay = TestClient(app)
    replay.cookies.set("relayops_session", token)
    assert replay.get("/api/auth/me").status_code == 401


def test_expired_session_is_rejected(db):
    build_world(db)
    c = login(TestClient(app), "support@a.test")
    db.execute(AuthSession.__table__.update().values(expires_at=utcnow() - timedelta(seconds=1)))
    db.commit()
    assert c.get("/api/auth/me").status_code == 401


def test_mutation_without_csrf_token_is_rejected(db):
    build_world(db)
    c = login(TestClient(app), "admin@a.test")
    body = {"name": "probe", "scopes": ["mcp:read"]}
    del c.headers["x-csrf-token"]
    assert c.post("/api/settings/tokens", json=body).status_code == 403
    c.headers["x-csrf-token"] = "forged"
    assert c.post("/api/settings/tokens", json=body).status_code == 403
    c.headers["x-csrf-token"] = c.cookies.get("relayops_csrf")
    c.headers["origin"] = "https://evil.example"
    assert c.post("/api/settings/tokens", json=body).status_code == 403
    c.headers["origin"] = "http://localhost:3020"
    assert c.post("/api/settings/tokens", json=body).status_code == 201
    # A CSRF token minted for another session does not transfer.
    other = login(TestClient(app), "support@a.test")
    c.headers["x-csrf-token"] = other.cookies.get("relayops_csrf")
    assert c.post("/api/settings/tokens", json=body).status_code == 403


def test_safe_redirect_rejects_offsite_and_cross_role_targets(db):
    build_world(db)
    for target, email, expected in [
        ("https://evil.example/app", "support@a.test", "/app"),
        ("//evil.example", "support@a.test", "/app"),
        ("/\\evil.example", "support@a.test", "/app"),
        ("/app/settings", "cust1@a.test", "/portal"),
        ("/portal/tickets/x", "cust1@a.test", "/portal/tickets/x"),
    ]:
        r = TestClient(app).post(
            "/api/auth/login", json={"email": email, "password": PASSWORD, "next": target}, headers=HEADERS
        )
        assert r.json()["redirect_to"] == expected, target


def test_registration_creates_new_org_and_cannot_join_existing_one(db):
    w = build_world(db)
    c = TestClient(app)
    r = c.post(
        "/api/auth/register",
        headers=HEADERS,
        json={
            "name": "Mallory",
            "email": "mallory@x.test",
            "password": "a-very-long-password",
            "organization_name": "Org A",
            "role": "admin",
            "organization_id": w.org_a,
        },
    )
    assert r.status_code == 200
    m = db.execute(select(Membership).join(User).where(User.email == "mallory@x.test")).scalar_one()
    assert m.organization_id != w.org_a and m.role == "admin"
    # The new admin's organization contains only the new admin.
    c.headers["x-csrf-token"] = c.cookies.get("relayops_csrf")
    assert [x["email"] for x in c.get("/api/settings/members").json()] == ["mallory@x.test"]


def test_registration_validates_password_and_duplicate_email(db):
    build_world(db)
    c = TestClient(app)
    short = c.post(
        "/api/auth/register",
        headers=HEADERS,
        json={"name": "X", "email": "x@x.test", "password": "short", "organization_name": "X"},
    )
    assert short.status_code == 422
    dup = c.post(
        "/api/auth/register",
        headers=HEADERS,
        json={"name": "X", "email": "support@a.test", "password": "long-enough-password", "organization_name": "X"},
    )
    assert dup.status_code == 409


def test_invitation_grants_only_customer_role_for_one_account(db):
    w = build_world(db)
    admin = login(TestClient(app), "admin@a.test")
    r = admin.post("/api/settings/invitations", json={"email": "new@a1.test", "customer_account_id": w.acct_a1})
    assert r.status_code == 201
    token = r.json()["token"]
    c = TestClient(app)
    r = c.post(
        "/api/auth/accept-invitation",
        headers=HEADERS,
        json={"token": token, "name": "New", "password": "another-long-password"},
    )
    assert r.status_code == 200 and r.json()["redirect_to"] == "/portal"
    m = db.execute(select(Membership).join(User).where(User.email == "new@a1.test")).scalar_one()
    assert (m.role, m.customer_account_id) == ("customer", w.acct_a1)
    again = TestClient(app).post(
        "/api/auth/accept-invitation",
        headers=HEADERS,
        json={"token": token, "name": "New", "password": "another-long-password"},
    )
    assert again.status_code == 422
    support = login(TestClient(app), "support@a.test")
    assert (
        support.post(
            "/api/settings/invitations", json={"email": "z@a.test", "customer_account_id": w.acct_a1}
        ).status_code
        == 403
    )
    other = login(TestClient(app), "admin@b.test")
    assert (
        other.post(
            "/api/settings/invitations", json={"email": "z@a.test", "customer_account_id": w.acct_a1}
        ).status_code
        == 404
    )
