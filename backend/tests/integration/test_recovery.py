"""Restart, lease, cancellation, replay, model failure, and budget behavior with the fixture provider."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select, update

from relayops.agents import llm
from relayops.agents.checkpoint import get_checkpointer
from relayops.agents.graph import build_graph
from relayops.core.clock import utcnow
from relayops.core.db import new_session, session_scope
from relayops.models import ActionRecord, InvestigationRun, Job, Proposal, RunEvent
from relayops.services import runs
from relayops.workers import worker
from tests.agent_helpers import CUSTOMER, SUPPORT, client, drain, export_bug_script, export_ticket, seeded, use_script


def _setup(db, tmp_path, script=None):
    creds = seeded(db, tmp_path)
    use_script(script or export_bug_script())
    cust, support = client(CUSTOMER, creds), client(SUPPORT, creds)
    tid = export_ticket(cust)
    run_id = support.post(f"/api/tickets/{tid}/investigations", json={"playbook_key": "bug"}).json()["id"]
    return cust, support, tid, run_id


def _run(run_id):
    with new_session() as s:
        return s.get(InvestigationRun, run_id)


def test_pending_review_survives_restart_and_resumes_same_thread(db, tmp_path):
    cust, support, tid, run_id = _setup(db, tmp_path)
    drain()
    thread = _run(run_id).thread_id
    # Simulate a fresh process: a new compiled graph over the same Postgres checkpointer.
    worker._graph = None
    fresh = build_graph(get_checkpointer())
    snap = fresh.get_state({"configurable": {"thread_id": thread}})
    assert snap.next == ("review",)
    assert snap.values["proposal_id"]
    # Re-delivering the original investigate job does not re-run anything.
    with session_scope() as s:
        s.execute(update(Job).where(Job.run_id == run_id).values(status="queued"))
    before = support.get(f"/api/investigations/{run_id}").json()["last_seq"]
    drain()
    assert support.get(f"/api/investigations/{run_id}").json()["last_seq"] == before
    prop = [p for p in support.get(f"/api/investigations/{run_id}").json()["proposals"]][0]
    support.post(
        f"/api/proposals/{prop['id']}/approve",
        json={
            "expected_version": 1,
            "expected_payload_hash": prop["payload_hash"],
            "acknowledge_uncertain_claims": True,
        },
    )
    drain()
    assert _run(run_id).status == "completed"
    assert len(cust.get(f"/api/tickets/{tid}").json()["messages"]) == 2


def test_crash_mid_investigation_resumes_from_checkpoint(db, tmp_path):
    calls = {"investigate": 0}
    base = export_bug_script()

    def flaky(purpose, user):
        if purpose == "investigate":
            calls["investigate"] += 1
            if calls["investigate"] == 2:
                raise RuntimeError("worker crashed mid-run")
        return base(purpose, user)

    _, support, _, run_id = _setup(db, tmp_path, flaky)
    drain()
    run = _run(run_id)
    assert run.status == "awaiting_review"
    with new_session() as s:
        jobs = s.execute(select(Job).where(Job.run_id == run_id)).scalars().all()
        extracts = s.execute(
            select(func.count(RunEvent.id)).where(
                RunEvent.run_id == run_id, RunEvent.kind == "model_call", RunEvent.node == "extract"
            )
        ).scalar_one()
    assert jobs[0].attempts == 2  # retried once after the crash
    assert extracts == 1  # extract was checkpointed and not repeated on resume


def test_expired_lease_is_recovered_and_old_owner_cannot_finish(db, tmp_path):
    _, support, _, run_id = _setup(db, tmp_path)
    with session_scope() as s:
        job = runs.claim_job(s, "worker-a", lease_seconds=60)
        assert job is not None
        job_id = job.id
    with session_scope() as s:  # nobody else can claim a live lease
        assert runs.claim_job(s, "worker-b", lease_seconds=60) is None
        s.execute(update(Job).where(Job.id == job_id).values(lease_expires_at=utcnow() - timedelta(seconds=1)))
    assert worker.process_one("worker-b")
    assert _run(run_id).status == "awaiting_review"
    runs.finish_job(job_id, "worker-a", "failed", "late")  # stale owner: no effect
    assert runs.heartbeat(job_id, "worker-a", 60) is False
    with new_session() as s:
        j = s.get(Job, job_id)
        assert j.status == "done" and j.lease_owner == "worker-b"


def test_advisory_lock_prevents_concurrent_advancement(db, tmp_path):
    _, _, _, run_id = _setup(db, tmp_path)
    with worker.run_lock(run_id) as locked:
        assert locked
        assert worker.process_one("worker-b")  # finds the job but must not advance it
        assert _run(run_id).status == "queued"
        with new_session() as s:
            assert s.execute(select(Job.status).where(Job.run_id == run_id)).scalar_one() == "queued"
    drain()
    assert _run(run_id).status == "awaiting_review"


def test_cancel_before_work_and_after_effects(db, tmp_path):
    _, support, _, run_id = _setup(db, tmp_path)
    r = support.post(f"/api/investigations/{run_id}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    drain()
    with new_session() as s:
        assert (
            s.execute(
                select(func.count(RunEvent.id)).where(RunEvent.run_id == run_id, RunEvent.kind == "model_call")
            ).scalar_one()
            == 0
        )
    assert support.post(f"/api/investigations/{run_id}/cancel").status_code == 409


def test_cancel_after_completed_action_does_not_claim_undo(db, tmp_path):
    cust, support, tid, run_id = _setup(db, tmp_path)
    drain()
    prop = support.get(f"/api/investigations/{run_id}").json()["proposals"][0]
    support.post(
        f"/api/proposals/{prop['id']}/approve",
        json={
            "expected_version": 1,
            "expected_payload_hash": prop["payload_hash"],
            "acknowledge_uncertain_claims": True,
        },
    )
    drain()
    r = support.post(f"/api/investigations/{run_id}/cancel")
    assert r.status_code == 409  # completed; the reply stays posted
    assert len(cust.get(f"/api/tickets/{tid}").json()["messages"]) == 2


def test_cancel_while_awaiting_review_blocks_approval(db, tmp_path):
    _, support, _, run_id = _setup(db, tmp_path)
    drain()
    prop = support.get(f"/api/investigations/{run_id}").json()["proposals"][0]
    assert support.post(f"/api/investigations/{run_id}/cancel").json()["status"] == "cancelled"
    r = support.post(
        f"/api/proposals/{prop['id']}/approve",
        json={
            "expected_version": 1,
            "expected_payload_hash": prop["payload_hash"],
            "acknowledge_uncertain_claims": True,
        },
    )
    assert r.status_code == 409


def test_recorded_replay_is_labeled_and_executes_nothing(db, tmp_path):
    cust, support, tid, run_id = _setup(db, tmp_path)
    drain()
    prop = support.get(f"/api/investigations/{run_id}").json()["proposals"][0]
    support.post(
        f"/api/proposals/{prop['id']}/approve",
        json={
            "expected_version": 1,
            "expected_payload_hash": prop["payload_hash"],
            "acknowledge_uncertain_claims": True,
        },
    )
    drain()
    provider = llm.get_provider()
    calls_before = len(provider.calls)  # type: ignore[attr-defined]
    rep = support.post(f"/api/investigations/{run_id}/replay")
    assert rep.status_code == 201
    replay = support.get(f"/api/investigations/{rep.json()['id']}").json()
    assert replay["run"]["mode"] == "recorded_replay" and replay["run"]["replay_of_run_id"] == run_id
    assert replay["proposals"] == [] and replay["actions"] == []
    assert replay["events"][0]["payload"]["label"].startswith("RECORDED REPLAY")
    assert len(provider.calls) == calls_before  # type: ignore[attr-defined]
    drain()
    with new_session() as s:
        assert s.execute(select(func.count(ActionRecord.id))).scalar_one() == 1
    assert len(cust.get(f"/api/tickets/{tid}").json()["messages"]) == 2
    # The executed proposal cannot be approved again.
    again = support.post(
        f"/api/proposals/{prop['id']}/approve",
        json={
            "expected_version": 1,
            "expected_payload_hash": prop["payload_hash"],
            "acknowledge_uncertain_claims": True,
        },
    )
    assert again.status_code == 409


def test_compare_run_needs_its_own_review(db, tmp_path):
    _, support, _, run_id = _setup(db, tmp_path)
    drain()
    prop = support.get(f"/api/investigations/{run_id}").json()["proposals"][0]
    support.post(
        f"/api/proposals/{prop['id']}/approve",
        json={
            "expected_version": 1,
            "expected_payload_hash": prop["payload_hash"],
            "acknowledge_uncertain_claims": True,
        },
    )
    drain()
    use_script(export_bug_script())
    cmp = support.post(f"/api/investigations/{run_id}/compare", json={"retrieval_mode": "lexical"})
    assert cmp.status_code == 201, cmp.text
    drain()
    d = support.get(f"/api/investigations/{cmp.json()['id']}").json()
    assert d["run"]["compare_of_run_id"] == run_id and d["run"]["status"] == "awaiting_review"
    assert d["run"]["retrieval_config"]["mode"] == "lexical"
    assert d["proposals"][0]["status"] == "pending_review" and d["actions"] == []


def test_model_unavailable_fails_visibly_and_retry_resumes(db, tmp_path):
    base = export_bug_script()
    state = {"down": True}

    def script(purpose, user):
        if state["down"] and purpose == "investigate":
            raise llm.ModelUnavailable("Ollama unreachable: ConnectError")
        return base(purpose, user)

    _, support, _, run_id = _setup(db, tmp_path, script)
    drain()
    d = support.get(f"/api/investigations/{run_id}").json()
    assert d["run"]["status"] == "failed" and "model unavailable" in d["run"]["error"]
    assert any(e["kind"] == "model_unavailable" for e in d["events"])
    state["down"] = False
    assert support.post(f"/api/investigations/{run_id}/retry").status_code == 200
    drain()
    assert _run(run_id).status == "awaiting_review"


def test_malformed_output_gets_one_repair_then_safe_handoff(db, tmp_path):
    def script(purpose, user):
        if purpose == "extract":
            return {
                "intent": "bug",
                "component": "exports",
                "product_version": "2.4",
                "error_code": "EXPORT_500",
                "first_seen": None,
                "summary": "s",
            }
        if purpose in ("investigate", "propose"):
            return '{"purpose": "x", "action": "call_tools", "tool_calls": [{"tool": "rm -rf", '  # truncated JSON
        return {"reply": "A support specialist is reviewing this.", "evidence_ids": []}

    _, support, _, run_id = _setup(db, tmp_path, script)
    drain()
    d = support.get(f"/api/investigations/{run_id}").json()
    model_events = [e for e in d["events"] if e["kind"] == "model_call"]
    assert [e["payload"]["valid"] for e in model_events if e["node"] == "investigate"] == [False, False]
    assert d["run"]["usage"]["repairs"] == 1
    assert d["run"]["route"] == "specialist_review" and d["run"]["verdict"] == "insufficient_evidence"
    assert d["run"]["usage"]["tool_calls"] == 0


def test_budgets_are_enforced_by_code(db, tmp_path):
    def script(purpose, user):
        base = export_bug_script()
        if purpose == "investigate":
            n = user.count("- turn ")
            return {
                "purpose": "Keep searching.",
                "action": "call_tools",
                "tool_calls": [
                    {"tool": "search_knowledge", "args": {"query": f"export attempt {n} a"}},
                    {"tool": "search_knowledge", "args": {"query": f"export attempt {n} b"}},
                    {"tool": "search_knowledge", "args": {"query": f"export attempt {n} c"}},
                ],
            }
        return base(purpose, user)

    _, support, _, run_id = _setup(db, tmp_path, script)
    drain()
    d = support.get(f"/api/investigations/{run_id}").json()
    assert d["run"]["usage"]["tool_calls"] == 6 and d["run"]["usage"]["turns"] == 3
    assert sum(1 for e in d["events"] if e["kind"] == "tool_call") == 6
    stop = [e for e in d["events"] if e["kind"] == "node_completed" and e["node"] == "investigate"][-1]
    assert stop["payload"]["stop_reason"] == "budget_exhausted"
    assert d["run"]["status"] == "awaiting_review"


def test_deadline_stops_investigation_with_handoff(db, tmp_path):
    _, support, _, run_id = _setup(db, tmp_path)
    with session_scope() as s:
        run = s.get(InvestigationRun, run_id)
        run.budgets = {**run.budgets, "deadline_seconds": 0}
    drain()
    d = support.get(f"/api/investigations/{run_id}").json()
    assert d["run"]["route"] == "specialist_review" and d["run"]["status"] == "awaiting_review"
    assert d["run"]["usage"]["model_calls"] == 0


def test_link_route_downgraded_when_issue_version_does_not_match(db, tmp_path):
    creds = seeded(db, tmp_path)
    use_script(export_bug_script())
    cust, support = client(CUSTOMER, creds), client(SUPPORT, creds)
    r = cust.post(
        "/api/tickets",
        json={
            "subject": "Export fails",
            "body": "EXPORT_500 on export",
            "component": "exports",
            "product_version": "2.2",
            "error_code": "EXPORT_500",
        },
    )
    tid = r.json()["ticket"]["id"]
    run_id = support.post(f"/api/tickets/{tid}/investigations", json={"playbook_key": "bug"}).json()["id"]
    drain()
    d = support.get(f"/api/investigations/{run_id}").json()
    prop = d["proposals"][0]
    # ENG-114 matches 2.2 and EXPORT_500, so the corrected link is to ENG-114, never ENG-101 (2.4 only).
    assert prop["payload"]["issue_key"] == "ENG-114"
    assert any("corrected" in o for o in prop["payload"]["overrides"])
    with new_session() as s:
        assert s.execute(select(Proposal.verification_status).where(Proposal.id == prop["id"])).scalar_one() == "passed"
