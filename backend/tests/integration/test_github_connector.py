"""Outbound GitHub Issues connector against a local GitHub-shaped HTTP service."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from relayops.core.db import new_session
from relayops.models import ActionRecord, Connection, OutboxMessage
from relayops.services import actions, github_connector
from tests.agent_helpers import ADMIN, CUSTOMER, SUPPORT, client, drain, seeded, use_script
from tests.support.github_fake import FakeGitHub


def _script(purpose, user):
    if purpose == "extract":
        return {
            "intent": "bug",
            "component": "exports",
            "product_version": "2.5",
            "error_code": "EXPORT_500",
            "first_seen": None,
            "summary": "small exports fail on 2.5",
        }
    if purpose == "draft_reply":
        return {
            "reply": "Thanks for the report. We have passed this to engineering and will update you.",
            "evidence_ids": [],
        }
    return {}


@pytest.fixture
def env(db, tmp_path):
    creds = seeded(db, tmp_path)
    use_script(_script)
    with FakeGitHub() as gh:
        yield {
            "gh": gh,
            "admin": client(ADMIN, creds),
            "support": client(SUPPORT, creds),
            "cust": client(CUSTOMER, creds),
        }


def _connect(env, token=None, name="Test tracker"):
    r = env["admin"].post(
        "/api/integrations/github",
        json={
            "name": name,
            "base_url": env["gh"].url,
            "repo": env["gh"].repo,
            "token": token or env["gh"].token,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["connection"]["id"]


def _approved_handoff(env) -> str:
    tid = (
        env["cust"]
        .post(
            "/api/tickets",
            json={
                "subject": "Exports fail on 2.5",
                "body": "Even small CSV exports fail with EXPORT_500 since 2.5.",
                "component": "exports",
                "product_version": "2.5",
                "error_code": "EXPORT_500",
            },
        )
        .json()["ticket"]["id"]
    )
    from relayops.services import runs
    from tests.factories import principal

    with new_session() as s:
        run = runs.start_run(s, principal(s, SUPPORT), tid, playbook_key="bug", execution="selective")
        s.commit()
        run_id = run.id
    drain()
    prop = env["support"].get(f"/api/investigations/{run_id}").json()["proposals"][0]
    assert prop["route"] == "new_engineering_handoff", prop["route"]
    r = env["support"].post(
        f"/api/proposals/{prop['id']}/approve",
        json={
            "expected_version": prop["version"],
            "expected_payload_hash": prop["payload_hash"],
            "acknowledge_uncertain_claims": True,
        },
    )
    assert r.status_code == 200, r.text
    drain()
    return prop["id"]


def _state(prop_id):
    with new_session() as s:
        rec = s.execute(select(ActionRecord).where(ActionRecord.proposal_id == prop_id)).scalar_one()
        msg = s.execute(
            select(OutboxMessage).where(
                OutboxMessage.action_id == rec.id, OutboxMessage.topic == github_connector.TOPIC
            )
        ).scalar_one()
        return rec.status, rec.receipt, msg.status, msg.attempts


def _deliver_now():
    with new_session() as s:
        for m in s.execute(select(OutboxMessage).where(OutboxMessage.status == "pending")).scalars():
            m.payload = {k: v for k, v in m.payload.items() if k != "next_attempt_at"}
        actions.deliver_outbox(s)
        s.commit()


def test_remote_hosts_are_refused_without_a_live_authorization(env):
    for url in ("https://api.github.com", "http://10.0.0.5", "http://example.test"):
        r = env["admin"].post(
            "/api/integrations/github", json={"name": "x", "base_url": url, "repo": "a/b", "token": "t"}
        )
        assert r.status_code == 422 and "separately authorized" in r.text
    assert (
        env["support"]
        .post("/api/integrations/github", json={"name": "x", "base_url": env["gh"].url, "repo": "a/b", "token": "t"})
        .status_code
        == 403
    )
    assert env["gh"].requests == []  # nothing was contacted


def test_connection_status_reflects_a_real_check(env):
    bad = _connect(env, token="wrong", name="Wrong token")
    res = env["admin"].post(f"/api/integrations/{bad}/test").json()
    assert not res["ok"] and res["status"] == "degraded" and "401" in res["error"]
    good = _connect(env)
    dup = env["admin"].post(
        "/api/integrations/github",
        json={"name": "Test tracker", "base_url": env["gh"].url, "repo": env["gh"].repo, "token": env["gh"].token},
    )
    assert dup.status_code == 409
    assert env["admin"].post(f"/api/integrations/{good}/test").json() == {
        "ok": True,
        "status": "healthy",
        "repository": env["gh"].repo,
    }
    listed = {c["id"]: c for c in env["admin"].get("/api/integrations").json()}
    assert listed[good]["status"] == "healthy" and listed[bad]["last_error"]
    with new_session() as s:
        assert env["gh"].token.encode() not in s.get(Connection, good).secret_encrypted  # stored encrypted


def test_handoff_is_mirrored_once_with_a_marker(env):
    _connect(env)
    prop_id = _approved_handoff(env)
    status, receipt, msg_status, _ = _state(prop_id)
    assert status == "succeeded" and msg_status == "delivered"
    assert receipt["external"]["status"] == "created" and receipt["external"]["issue"] == f"{env['gh'].repo}#1"
    issue = env["gh"].issues[0]
    assert "relayops:action:" in issue["body"] and issue["labels"] == ["relayops"]
    _deliver_now()
    assert len(env["gh"].issues) == 1  # delivered messages are not sent again


def test_lost_response_is_reconciled_by_marker_not_recreated(env):
    _connect(env)
    env["gh"].mode = "lose_response"
    prop_id = _approved_handoff(env)
    _, receipt, msg_status, attempts = _state(prop_id)
    assert msg_status == "pending" and receipt["external"]["status"] == "unknown" and attempts == 1
    assert len(env["gh"].issues) == 1  # it was created remotely; we just don't know yet
    env["gh"].mode = "ok"
    _deliver_now()
    _, receipt, msg_status, _ = _state(prop_id)
    assert msg_status == "delivered" and receipt["external"]["status"] == "reconciled"
    assert len(env["gh"].issues) == 1


def test_rejection_and_persistent_errors_are_visible_and_local_action_stands(env):
    _connect(env)
    env["gh"].mode = "reject"
    prop_id = _approved_handoff(env)
    status, receipt, msg_status, _ = _state(prop_id)
    assert status == "succeeded" and msg_status == "failed" and receipt["external"]["status"] == "rejected"
    assert receipt["engineering_issue_key"].startswith("LOCAL-")


def test_server_errors_give_up_after_bounded_attempts(env):
    _connect(env)
    env["gh"].mode = "server_error"
    prop_id = _approved_handoff(env)
    for _ in range(github_connector.MAX_ATTEMPTS):
        _deliver_now()
    _, receipt, msg_status, attempts = _state(prop_id)
    assert msg_status == "failed" and attempts == github_connector.MAX_ATTEMPTS
    assert "operator decision required" in receipt["external"]["error"] and env["gh"].issues == []


def test_disabling_before_delivery_sends_nothing(env):
    cid = _connect(env)
    env["gh"].mode = "server_error"
    prop_id = _approved_handoff(env)
    env["admin"].post(f"/api/integrations/{cid}/disable")
    _deliver_now()
    _, receipt, msg_status, _ = _state(prop_id)
    assert msg_status == "failed" and receipt["external"]["status"] == "not_sent"
