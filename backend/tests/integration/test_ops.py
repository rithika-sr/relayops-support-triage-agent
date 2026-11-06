"""Liveness, readiness, request IDs, structured logs, and several workers sharing one queue."""

from __future__ import annotations

import json
import logging
import threading

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from relayops.api import main
from relayops.core import logs
from relayops.core.db import new_session
from relayops.models import InvestigationRun, Job
from relayops.workers import worker
from tests.agent_helpers import CUSTOMER, SUPPORT, client, export_bug_script, seeded, use_script


def test_liveness_and_readiness(db, monkeypatch):
    with TestClient(main.app) as c:
        assert c.get("/api/health").json() == {"status": "ok"}
        r = c.get("/api/ready")
        assert r.status_code == 200, r.text
        checks = r.json()["checks"]
        assert checks["migrations"]["ok"] and checks["data_mode"]["mode"] == "test" and checks["mcp"]["ok"]
        monkeypatch.setattr(main, "_migration_head", lambda: "9999")
        r = c.get("/api/ready")
        assert r.status_code == 503 and r.json()["checks"]["migrations"] == {
            "ok": False,
            "current": r.json()["checks"]["migrations"]["current"],
            "head": "9999",
        }


def test_request_ids_are_echoed_or_replaced(db):
    c = TestClient(main.app)
    assert c.get("/api/health", headers={"X-Request-ID": "abc12345-xyz"}).headers["X-Request-ID"] == "abc12345-xyz"
    replaced = c.get("/api/health", headers={"X-Request-ID": "bad id\nwith newline"}).headers["X-Request-ID"]
    assert len(replaced) == 32 and "\n" not in replaced


def test_json_log_lines_carry_request_id_and_no_query_or_secrets(db):
    fmt = logs.JsonFormatter()
    records: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(fmt.format(record))

    h = Capture()
    logs.enable_app_loggers()
    lg = logging.getLogger("relayops.api")
    lg.addHandler(h)
    lg.setLevel(logging.INFO)
    try:
        TestClient(main.app).get(
            "/api/tickets?q=secret-search", headers={"X-Request-ID": "req-0000001", "Authorization": "Bearer rlo_x"}
        )
    finally:
        lg.removeHandler(h)
    line = json.loads(next(r for r in records if '"request"' in r))
    assert line["request_id"] == "req-0000001" and line["path"] == "/api/tickets" and line["status"] == 401
    assert "secret-search" not in json.dumps(line) and "rlo_x" not in json.dumps(line)


def test_several_workers_share_the_queue_without_double_work(db, tmp_path):
    creds = seeded(db, tmp_path)
    use_script(export_bug_script())
    cust, support = client(CUSTOMER, creds), client(SUPPORT, creds)
    run_ids = []
    for i in range(4):
        tid = cust.post(
            "/api/tickets",
            json={
                "subject": f"CSV export fails {i}",
                "body": "EXPORT_500 on big export",
                "component": "exports",
                "product_version": "2.4",
                "error_code": "EXPORT_500",
            },
        ).json()["ticket"]["id"]
        run_ids.append(support.post(f"/api/tickets/{tid}/investigations", json={"playbook_key": "bug"}).json()["id"])
    errors: list[BaseException] = []

    def work(n: int) -> None:
        try:
            while worker.process_one(f"w{n}"):
                pass
        except BaseException as exc:  # noqa: BLE001 - surfaced by the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(n,)) for n in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    assert not errors
    with new_session() as s:
        statuses = dict(
            s.execute(
                select(InvestigationRun.id, InvestigationRun.status).where(InvestigationRun.id.in_(run_ids))
            ).all()
        )
        assert set(statuses.values()) == {"awaiting_review"}, statuses
        open_jobs = s.execute(select(func.count(Job.id)).where(Job.status.in_(("queued", "running")))).scalar_one()
        assert open_jobs == 0
        per_run = dict(
            s.execute(select(Job.run_id, func.count(Job.id)).where(Job.run_id.in_(run_ids)).group_by(Job.run_id)).all()
        )
        assert all(n == 1 for n in per_run.values()), per_run  # one start job each, claimed once
