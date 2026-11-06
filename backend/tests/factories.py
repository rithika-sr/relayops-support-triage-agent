"""Small world builder for tests: two organizations, several accounts, staff and customers."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from relayops.core.security import hash_password
from relayops.domain.scope import Principal
from relayops.models import CustomerAccount, Membership, Organization, User

PASSWORD = "correct-horse-battery-staple"


@dataclass
class World:
    org_a: str = "org_a"
    org_b: str = "org_b"
    acct_a1: str = "acct_a1"
    acct_a2: str = "acct_a2"
    acct_b1: str = "acct_b1"


def build_world(db: Session) -> World:
    w = World()
    db.add_all(
        [
            Organization(id=w.org_a, name="Org A", slug="org-a"),
            Organization(id=w.org_b, name="Org B", slug="org-b"),
        ]
    )
    db.flush()
    db.add_all(
        [
            CustomerAccount(
                id=w.acct_a1, organization_id=w.org_a, name="A One", plan="business", product_version="2.4"
            ),
            CustomerAccount(
                id=w.acct_a2, organization_id=w.org_a, name="A Two", plan="enterprise", product_version="2.5"
            ),
            CustomerAccount(
                id=w.acct_b1, organization_id=w.org_b, name="B One", plan="business", product_version="2.4"
            ),
        ]
    )
    db.flush()
    for email, org, role, acct in [
        ("admin@a.test", w.org_a, "admin", None),
        ("support@a.test", w.org_a, "support", None),
        ("cust1@a.test", w.org_a, "customer", w.acct_a1),
        ("cust2@a.test", w.org_a, "customer", w.acct_a2),
        ("admin@b.test", w.org_b, "admin", None),
        ("support@b.test", w.org_b, "support", None),
        ("cust@b.test", w.org_b, "customer", w.acct_b1),
    ]:
        u = User(
            id="usr_" + email.replace("@", "_").replace(".", "_"),
            email=email,
            name=email.split("@")[0],
            password_hash=hash_password(PASSWORD),
        )
        db.add(u)
        db.flush()
        db.add(Membership(id="mem_" + u.id[4:], user_id=u.id, organization_id=org, role=role, customer_account_id=acct))
    db.commit()
    return w


def principal(db: Session, email: str) -> Principal:
    u = db.query(User).filter_by(email=email).one()
    m = db.query(Membership).filter_by(user_id=u.id).one()
    return Principal(
        user_id=u.id,
        email=u.email,
        name=u.name,
        membership_id=m.id,
        organization_id=m.organization_id,
        role=m.role,
        customer_account_id=m.customer_account_id,
    )


HEADERS = {"x-requested-with": "relayops", "origin": "http://localhost:3020"}


def login(client: TestClient, email: str, password: str = PASSWORD) -> TestClient:
    r = client.post("/api/auth/login", json={"email": email, "password": password}, headers=HEADERS)
    assert r.status_code == 200, r.text
    client.headers.update(
        {"x-csrf-token": client.cookies.get("relayops_csrf") or "", "origin": "http://localhost:3020"}
    )
    return client


def client_for(email: str) -> TestClient:
    from relayops.api.main import app

    return login(TestClient(app), email)
