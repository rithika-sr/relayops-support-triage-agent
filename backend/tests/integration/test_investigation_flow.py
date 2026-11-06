"""Runtime journey with the labeled fixture provider: ticket -> investigation -> review -> local action."""

from __future__ import annotations

import threading

from sqlalchemy import func, select

from relayops.core.db import new_session
from relayops.models import ActionRecord, AuditEvent, Job, OutboxMessage, Proposal, Ticket, TicketIssueLink
from tests.agent_helpers import (
    ADMIN,
    CUSTOMER,
    SUPPORT,
    client,
    drain,
    export_bug_script,
    export_ticket,
    seeded,
    use_script,
)


def _start(support, ticket_id, **body):
    r = support.post(f"/api/tickets/{ticket_id}/investigations", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _pending(support, run_id):
    d = support.get(f"/api/investigations/{run_id}").json()
    return d, [p for p in d["proposals"] if p["status"] == "pending_review"][0]


def test_end_to_end_customer_sees_only_approved_reply(db, tmp_path):
    creds = seeded(db, tmp_path)
    provider = use_script(export_bug_script())
    cust, support = client(CUSTOMER, creds), client(SUPPORT, creds)
    tid = export_ticket(cust)
    inbox = support.get("/api/tickets?q=CSV export").json()["items"]
    assert inbox[0]["id"] == tid and inbox[0]["account_name"] == "Northstar Logistics"
    assert inbox[0]["target"]["policy"]["hours"] == 12  # business plan, normal priority
    run_id = _start(support, tid, playbook_key="bug")
    drain()
    detail, prop = _pending(support, run_id)
    assert detail["run"]["status"] == "awaiting_review"
    assert detail["run"]["model_provider"] == "fixture"
    assert prop["route"] == "link_existing_issue" and prop["payload"]["issue_key"] == "ENG-101"
    assert prop["verification_status"] == "passed", prop["verification"]
    assert {g["id"]: g["state"] for g in detail["graph"]}["review"] == "waiting"
    assert detail["run"]["usage"]["tool_calls"] == 2
    assert {c["purpose"] for c in provider.calls} >= {"extract", "investigate", "propose", "draft_reply"}

    # Drafting alone shows nothing to the customer and does not resolve the ticket.
    msgs = cust.get(f"/api/tickets/{tid}").json()["messages"]
    assert len(msgs) == 1
    assert cust.get(f"/api/investigations/{run_id}").status_code == 403

    unacked = support.post(
        f"/api/proposals/{prop['id']}/approve",
        json={"expected_version": prop["version"], "expected_payload_hash": prop["payload_hash"]},
    )
    assert unacked.status_code == 409 and "could not be confirmed" in unacked.text
    r = support.post(
        f"/api/proposals/{prop['id']}/approve",
        json={
            "expected_version": prop["version"],
            "expected_payload_hash": prop["payload_hash"],
            "acknowledge_uncertain_claims": True,
        },
    )
    assert r.status_code == 200, r.text
    drain()
    after = cust.get(f"/api/tickets/{tid}").json()
    assert [m["author_kind"] for m in after["messages"]] == ["customer", "staff"]
    assert "Prepare in background" in after["messages"][1]["body"]
    assert after["ticket"]["status"] == "pending_customer"
    detail = support.get(f"/api/investigations/{run_id}").json()
    assert detail["run"]["status"] == "completed"
    assert detail["actions"][0]["status"] == "succeeded" and detail["actions"][0]["adapter"] == "local"
    with new_session() as s:
        assert (
            s.execute(select(func.count(TicketIssueLink.id)).where(TicketIssueLink.ticket_id == tid)).scalar_one() == 1
        )
        assert (
            s.execute(select(func.count(OutboxMessage.id)).where(OutboxMessage.status == "delivered")).scalar_one() == 1
        )
        actions = {a for (a,) in s.execute(select(AuditEvent.action)).all()}
    assert {"ticket.created", "investigation.started", "proposal.approved", "action.executed"} <= actions
    admin = client(ADMIN, creds)
    audit = admin.get("/api/audit?action=action").json()
    assert any(e["action"] == "action.executed" for e in audit["items"])


def test_edit_supersedes_version_and_old_approval_fails(db, tmp_path):
    creds = seeded(db, tmp_path)
    use_script(export_bug_script())
    cust, support = client(CUSTOMER, creds), client(SUPPORT, creds)
    tid = export_ticket(cust)
    run_id = _start(support, tid, playbook_key="bug")
    drain()
    _, v1 = _pending(support, run_id)
    r = support.post(
        f"/api/proposals/{v1['id']}/edit",
        json={
            "customer_reply": "Our team is aware of this export problem. Please use Prepare in background meanwhile.",
            "expected_version": 1,
        },
    )
    assert r.status_code == 200, r.text
    v2 = r.json()
    assert v2["version"] == 2 and v2["payload_hash"] != v1["payload_hash"]
    stale = support.post(
        f"/api/proposals/{v1['id']}/approve",
        json={"expected_version": 1, "expected_payload_hash": v1["payload_hash"], "acknowledge_uncertain_claims": True},
    )
    assert stale.status_code == 409
    wrong_hash = support.post(
        f"/api/proposals/{v2['id']}/approve",
        json={"expected_version": 2, "expected_payload_hash": v1["payload_hash"], "acknowledge_uncertain_claims": True},
    )
    assert wrong_hash.status_code == 409
    ok = support.post(
        f"/api/proposals/{v2['id']}/approve",
        json={"expected_version": 2, "expected_payload_hash": v2["payload_hash"], "acknowledge_uncertain_claims": True},
    )
    assert ok.status_code == 200
    drain()
    msgs = cust.get(f"/api/tickets/{tid}").json()["messages"]
    assert msgs[-1]["body"].startswith("Our team is aware of this export problem")
    art = support.get("/api/artifacts?kind=customer_reply").json()[0]
    versions = support.get(f"/api/artifacts/{art['id']}").json()["versions"]
    assert [v["version"] for v in versions] == [2, 1]


def test_customer_message_during_review_makes_approval_stale(db, tmp_path):
    creds = seeded(db, tmp_path)
    use_script(export_bug_script())
    cust, support = client(CUSTOMER, creds), client(SUPPORT, creds)
    tid = export_ticket(cust)
    run_id = _start(support, tid, playbook_key="bug")
    drain()
    _, prop = _pending(support, run_id)
    cust.post(f"/api/tickets/{tid}/messages", json={"body": "Update: it now fails on 2.5 too."})
    r = support.post(
        f"/api/proposals/{prop['id']}/approve",
        json={
            "expected_version": 1,
            "expected_payload_hash": prop["payload_hash"],
            "acknowledge_uncertain_claims": True,
        },
    )
    assert r.status_code == 409 and "ticket_revision" in r.json()["detail"]
    detail, prop = _pending(support, run_id)
    assert "ticket_revision" in prop["stale_reasons"]


def test_concurrent_approvals_produce_one_action(db, tmp_path):
    creds = seeded(db, tmp_path)
    use_script(export_bug_script())
    cust, support = client(CUSTOMER, creds), client(SUPPORT, creds)
    admin = client(ADMIN, creds)
    run_id = _start(support, export_ticket(cust), playbook_key="bug")
    drain()
    _, prop = _pending(support, run_id)
    body = {"expected_version": 1, "expected_payload_hash": prop["payload_hash"], "acknowledge_uncertain_claims": True}
    codes: list[int] = []

    def go(c):
        codes.append(c.post(f"/api/proposals/{prop['id']}/approve", json=body).status_code)

    threads = [threading.Thread(target=go, args=(c,)) for c in (support, admin, support, admin)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(codes) == [200, 409, 409, 409]
    drain()
    from relayops.services import actions

    with new_session() as s:
        assert s.execute(select(func.count(ActionRecord.id))).scalar_one() == 1
        review_id = s.execute(select(Proposal).where(Proposal.id == prop["id"])).scalar_one()
        rec = s.execute(select(ActionRecord)).scalar_one()
        again = actions.execute(s, prop["id"], rec.review_id)  # resume after crash: same record, no new effect
        assert again.id == rec.id and review_id
        s.commit()
        staff_msgs = s.execute(
            select(func.count())
            .select_from(Ticket)
            .where(Ticket.first_responded_at.is_not(None), Ticket.is_historical.is_(False))
        ).scalar_one()
        assert staff_msgs == 1


def test_reject_records_history_without_effect(db, tmp_path):
    creds = seeded(db, tmp_path)
    use_script(export_bug_script())
    cust, support = client(CUSTOMER, creds), client(SUPPORT, creds)
    tid = export_ticket(cust)
    run_id = _start(support, tid, playbook_key="bug")
    drain()
    _, prop = _pending(support, run_id)
    r = support.post(f"/api/proposals/{prop['id']}/reject", json={"expected_version": 1, "note": "wrong tone"})
    assert r.status_code == 200
    drain()
    d = support.get(f"/api/investigations/{run_id}").json()
    assert d["run"]["status"] == "rejected" and d["actions"] == []
    assert d["proposals"][0]["reviews"][0]["decision"] == "reject"
    assert len(cust.get(f"/api/tickets/{tid}").json()["messages"]) == 1


def test_other_org_cannot_touch_runs_events_or_proposals(db, tmp_path):
    creds = seeded(db, tmp_path)
    use_script(export_bug_script())
    cust, support = client(CUSTOMER, creds), client(SUPPORT, creds)
    run_id = _start(support, export_ticket(cust), playbook_key="bug")
    drain()
    _, prop = _pending(support, run_id)
    other = client("admin@quillstack.local", creds)
    for path in (
        f"/api/investigations/{run_id}",
        f"/api/investigations/{run_id}/events",
        f"/api/investigations/{run_id}/stream",
    ):
        assert other.get(path).status_code == 404, path
    assert (
        other.post(
            f"/api/proposals/{prop['id']}/approve",
            json={
                "expected_version": 1,
                "expected_payload_hash": prop["payload_hash"],
                "acknowledge_uncertain_claims": True,
            },
        ).status_code
        == 404
    )
    assert other.post(f"/api/investigations/{run_id}/cancel").status_code == 404
    assert other.get("/api/investigations").json()["items"] == []
    assert (
        cust.post(
            f"/api/proposals/{prop['id']}/approve",
            json={
                "expected_version": 1,
                "expected_payload_hash": prop["payload_hash"],
                "acknowledge_uncertain_claims": True,
            },
        ).status_code
        == 403
    )


def test_jobs_are_deduplicated_per_run(db, tmp_path):
    creds = seeded(db, tmp_path)
    use_script(export_bug_script())
    cust, support = client(CUSTOMER, creds), client(SUPPORT, creds)
    tid = export_ticket(cust)
    _start(support, tid, playbook_key="bug")
    assert support.post(f"/api/tickets/{tid}/investigations", json={}).status_code == 409
    with new_session() as s:
        assert s.execute(select(func.count(Job.id))).scalar_one() == 1


def test_generic_fixture_script_drives_the_full_runtime(db, tmp_path):
    from relayops.agents.fixture_scripts import generic_script

    creds = seeded(db, tmp_path)
    use_script(generic_script)
    cust, support = client(CUSTOMER, creds), client(SUPPORT, creds)
    tid = export_ticket(cust)
    run_id = _start(support, tid, playbook_key="bug")
    drain()
    _, prop = _pending(support, run_id)
    assert prop["route"] == "link_existing_issue" and prop["payload"]["issue_key"] == "ENG-101"
