"""Scripted (fixture) model behavior for runtime tests. These never claim to measure model quality."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from relayops.agents import llm
from relayops.core.db import new_session
from relayops.models import User
from relayops.services.seed import seed
from relayops.workers import worker
from tests.factories import HEADERS


def seeded(db, tmp_path) -> dict[str, str]:
    path = tmp_path / "creds.json"
    seed(db, credentials_path=path)
    db.commit()
    return {k: v["password"] for k, v in json.loads(path.read_text())["accounts"].items()}


def client(email: str, creds: dict[str, str]) -> TestClient:
    from relayops.api.main import app

    c = TestClient(app)
    r = c.post("/api/auth/login", json={"email": email, "password": creds[email]}, headers=HEADERS)
    assert r.status_code == 200, r.text
    c.headers.update({"x-csrf-token": c.cookies.get("relayops_csrf") or "", "origin": "http://localhost:3020"})
    return c


def find_id(user: str, pattern: str) -> str | None:
    m = re.search(r"\[(E\d+)\][^\n]*" + pattern, user)
    return m.group(1) if m else None


def export_bug_script(*, investigate_calls: list[list[dict[str, Any]]] | None = None) -> Callable[[str, str], Any]:
    """Investigate with two tools, then finish; link ENG-101; cite a public passage."""
    plan = investigate_calls or [
        [
            {"tool": "search_engineering_issues", "args": {"query": "EXPORT_500 export"}},
            {"tool": "search_knowledge", "args": {"query": "export large project background"}},
        ],
    ]
    turn = {"n": 0}

    def script(purpose: str, user: str) -> Any:
        if purpose == "extract":
            return {
                "intent": "bug",
                "component": "exports",
                "product_version": "2.4",
                "error_code": "EXPORT_500",
                "first_seen": None,
                "summary": "CSV export fails with EXPORT_500",
            }
        if purpose == "investigate":
            i = turn["n"]
            turn["n"] += 1
            if i < len(plan):
                return {
                    "purpose": "Check known issues and export guidance.",
                    "action": "call_tools",
                    "tool_calls": plan[i],
                }
            return {"purpose": "Evidence is sufficient.", "action": "finish", "tool_calls": []}
        if purpose == "propose":
            return {
                "route": "link_existing_issue",
                "rationale": "ENG-101 matches signature and version.",
                "evidence_ids": [],
                "issue_evidence_id": find_id(user, r"ENG-101"),
                "incident_evidence_id": None,
                "missing_facts": [],
                "clarifying_questions": [],
                "observations": ["EXPORT_500 on 2.4"],
                "hypotheses": [],
            }
        if purpose == "draft_reply":
            pub = find_id(user, r"public")
            return {
                "reply": "Our team is aware of export failures on large projects. Please use Prepare in "
                "background from the Export menu as a workaround.",
                "evidence_ids": [pub] if pub else [],
            }
        raise AssertionError(purpose)

    return script


def use_script(script: Callable[[str, str], Any]) -> llm.FixtureProvider:
    p = llm.FixtureProvider(script)
    llm.set_provider(p)
    return p


def drain(limit: int = 50) -> int:
    n = 0
    while worker.process_one("test-worker") and n < limit:
        n += 1
    return n


def user_id(email: str) -> str:
    with new_session() as db:
        return db.execute(select(User.id).where(User.email == email)).scalar_one()


CUSTOMER, SUPPORT, ADMIN = "customer@northstar.local", "support@relayops.local", "admin@relayops.local"


def export_ticket(c: TestClient) -> str:
    r = c.post(
        "/api/tickets",
        json={
            "subject": "CSV export fails",
            "body": "Fleet Planning export (80k tasks) fails with EXPORT_500.",
            "component": "exports",
            "product_version": "2.4",
            "error_code": "EXPORT_500",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["ticket"]["id"]
