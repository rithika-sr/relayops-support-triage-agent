"""Incident constellations, timelines, playbooks, artifacts, exports, and evaluation import."""

from __future__ import annotations

import json

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


def test_constellation_counts_distinct_accounts_and_needs_review(db, tmp_path):
    creds = seeded(db, tmp_path)
    support = client(SUPPORT, creds)
    cands = support.get("/api/incidents/candidates?window_hours=12").json()
    webhook = next(c for c in cands if c["signature"] == "WEBHOOK_SIG_MISMATCH")
    assert webhook["ticket_count"] == 3 and webhook["distinct_accounts"] == 2  # two Acme tickets + one Orbit
    assert webhook["status"] == "candidate" and webhook["linked_incidents"] == []
    narrow = support.get("/api/incidents/candidates?window_hours=1").json()
    assert not any(c["signature"] == "WEBHOOK_SIG_MISMATCH" and c["ticket_count"] == 3 for c in narrow)

    ids = [t["id"] for t in webhook["tickets"]]
    stale = support.post(
        f"/api/incidents/candidates/{webhook['key']}/confirm",
        json={
            "title": "Webhook signature failures",
            "severity": "P2",
            "window_hours": 12,
            "expected_ticket_ids": ids[:2],
        },
    )
    assert stale.status_code == 409
    ok = support.post(
        f"/api/incidents/candidates/{webhook['key']}/confirm",
        json={"title": "Webhook signature failures", "severity": "P2", "window_hours": 12, "expected_ticket_ids": ids},
    )
    assert ok.status_code == 201, ok.text
    inc = ok.json()["incident"]
    assert inc["linked_tickets"] == 3 and inc["affected_accounts"] == 2 and inc["public_visible"] is False
    timeline = ok.json()["timeline"]
    lanes = {x["lane"] for x in timeline}
    assert {"customer_report", "trusted_record", "signal"} <= lanes
    dep = next(x for x in timeline if x["kind"] == "deployment")
    assert "not a confirmed cause" in dep["note"]

    # Customers never see the unpublished incident; only admins can publish it.
    cust = client(CUSTOMER, creds)
    assert all(i["id"] != inc["id"] for i in cust.get("/api/incidents").json())
    assert cust.get(f"/api/incidents/{inc['id']}").status_code == 404
    assert cust.get("/api/incidents/candidates").status_code == 403
    assert (
        support.patch(
            f"/api/incidents/{inc['id']}", json={"public_visible": True, "public_summary": "Some webhooks fail."}
        ).status_code
        == 403
    )
    admin = client(ADMIN, creds)
    assert admin.patch(f"/api/incidents/{inc['id']}", json={"public_visible": True}).status_code == 422
    pub = admin.patch(
        f"/api/incidents/{inc['id']}",
        json={
            "public_visible": True,
            "public_summary": "Some webhook deliveries fail signature checks. We are investigating.",
        },
    )
    assert pub.status_code == 200
    seen = cust.get(f"/api/incidents/{inc['id']}").json()["incident"]
    assert set(seen) == {"id", "title", "component", "status", "started_at", "resolved_at", "public_summary"}
    # Other organization cannot see or confirm.
    other = client("admin@quillstack.local", creds)
    assert other.get(f"/api/incidents/{inc['id']}").status_code == 404
    assert all(c["signature"] != "WEBHOOK_SIG_MISMATCH" for c in other.get("/api/incidents/candidates").json())
    csv = support.get("/api/incidents/export.csv").text
    assert "Webhook signature failures" in csv and "QUILLSTACK" not in csv


def test_incident_summary_artifact_versions_and_revalidation(db, tmp_path):
    creds = seeded(db, tmp_path)
    support = client(SUPPORT, creds)
    inc_id = "inc_notify_lag"
    cands = support.get("/api/incidents/candidates?window_hours=12").json()
    notify = next(c for c in cands if c["signature"] == "NOTIFY_QUEUE_LAG")
    support.post(
        f"/api/incidents/candidates/{notify['key']}/confirm",
        json={"incident_id": inc_id, "window_hours": 12, "expected_ticket_ids": [t["id"] for t in notify["tickets"]]},
    )
    art = support.post(f"/api/incidents/{inc_id}/summary").json()["artifact_id"]
    v1 = support.post(f"/api/artifacts/{art}/revalidate").json()
    assert v1["verification_status"] == "passed"
    detail = support.get(f"/api/artifacts/{art}").json()
    wrong = detail["versions"][0]["content"].replace("Affected accounts: 2", "Affected accounts: 5")
    edited = support.post(f"/api/artifacts/{art}/versions", json={"content": wrong, "note": "typo"}).json()
    assert edited == {"version": 2, "verification_status": "stale"}
    again = support.post(f"/api/artifacts/{art}/revalidate").json()
    assert again["verification_status"] == "failed"
    md = support.get(f"/api/artifacts/{art}/export?format=md")
    assert md.status_code == 200 and "verification:failed" in md.text
    js = json.loads(support.get(f"/api/artifacts/{art}/export?format=json").text)
    assert [v["version"] for v in js["versions"]] == [2, 1]
    assert support.get(f"/api/artifacts/{art}/export?format=pdf").status_code == 422
    assert client(CUSTOMER, creds).get(f"/api/artifacts/{art}/export?format=md").status_code == 403
    assert client("admin@quillstack.local", creds).get(f"/api/artifacts/{art}").status_code == 404


def test_ticket_timeline_separates_reports_records_and_hypotheses(db, tmp_path):
    creds = seeded(db, tmp_path)
    use_script(
        export_bug_script(
            investigate_calls=[
                [
                    {"tool": "get_error_aggregates", "args": {"error_signature": "EXPORT_500"}},
                    {"tool": "search_engineering_issues", "args": {"query": "export"}},
                ]
            ]
        )
    )
    cust, support = client(CUSTOMER, creds), client(SUPPORT, creds)
    tid = export_ticket(cust)
    support.post(f"/api/tickets/{tid}/investigations", json={"playbook_key": "bug"})
    drain()
    tl = support.get(f"/api/tickets/{tid}/timeline").json()
    kinds = {(x["lane"], x["kind"]) for x in tl["items"]}
    assert ("customer_report", "message_customer") in kinds
    assert ("signal", "error_aggregate") in kinds and ("trusted_record", "issue") in kinds
    assert all("as_of" in x for x in tl["items"])
    assert cust.get(f"/api/tickets/{tid}/timeline").status_code == 403


def test_playbooks_are_typed_versioned_and_admin_editable(db, tmp_path):
    creds = seeded(db, tmp_path)
    support, admin = client(SUPPORT, creds), client(ADMIN, creds)
    pbs = support.get("/api/playbooks").json()
    assert {p["key"] for p in pbs} == {"howto", "bug", "feature", "incident"}
    d = support.get("/api/playbooks/howto").json()
    assert [n["id"] for n in d["graph"]["nodes"]][:4] == ["load_context", "extract", "precheck", "investigate"]
    cfg = {**d["config"], "max_turns": 2}
    assert support.post("/api/playbooks/howto/revisions", json={"config": cfg}).status_code == 403
    bad = admin.post("/api/playbooks/howto/revisions", json={"config": {**cfg, "allowed_tools": ["shell"]}})
    assert bad.status_code == 422
    too_big = admin.post("/api/playbooks/howto/revisions", json={"config": {**cfg, "max_tool_calls": 50}})
    assert too_big.status_code == 422
    ok = admin.post("/api/playbooks/howto/revisions", json={"config": cfg})
    assert ok.status_code == 201 and ok.json()["playbook"]["current_revision"] == 2
    assert set(ok.json()["config"]["allowed_routes"]) >= {"clarification", "specialist_review"}


def test_all_four_playbooks_execute_on_shared_runtime(db, tmp_path):
    creds = seeded(db, tmp_path)
    use_script(export_bug_script())
    cust, support = client(CUSTOMER, creds), client(SUPPORT, creds)
    statuses = {}
    for key in ("howto", "bug", "feature", "incident"):
        tid = export_ticket(cust)
        run = support.post(f"/api/tickets/{tid}/investigations", json={"playbook_key": key}).json()
        use_script(export_bug_script())
        drain()
        d = support.get(f"/api/investigations/{run['id']}").json()
        statuses[key] = (d["run"]["status"], d["run"]["playbook"])
    assert all(s == ("awaiting_review", k) for k, s in statuses.items()), statuses


def test_engineering_board_and_audit_are_role_scoped(db, tmp_path):
    creds = seeded(db, tmp_path)
    support = client(SUPPORT, creds)
    board = support.get("/api/engineering/board").json()
    keys = {i["key"] for col in board["columns"].values() for i in col}
    assert "ENG-101" in keys and not any(k.startswith("QS-") for k in keys)
    dup = next(d for d in board["duplicate_candidates"] if d["signature"] == "EXPORT_500")
    assert set(dup["issues"]) == {"ENG-101", "ENG-114"}
    eng101 = next(i for col in board["columns"].values() for i in col if i["key"] == "ENG-101")
    detail = support.get(f"/api/engineering/issues/{eng101['id']}").json()
    assert detail["distinct_accounts"] >= 1
    assert client(CUSTOMER, creds).get("/api/engineering/board").status_code == 403
    assert support.get("/api/audit").status_code == 403
    assert client(ADMIN, creds).get("/api/audit").status_code == 200
