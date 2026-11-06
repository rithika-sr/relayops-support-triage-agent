"""Single durable worker.

Jobs are claimed in a short transaction with a lease. A heartbeat thread extends the lease while the graph
runs; if the process dies the lease expires and another worker may claim the job. A session-level Postgres
advisory lock keyed by run ID guarantees that only one process advances a run's thread at a time, even if a
slow worker outlives its lease. No database transaction is held open during inference.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import time
from contextlib import contextmanager
from typing import Any

import psycopg
from langgraph.types import Command

from relayops.agents.checkpoint import get_checkpointer
from relayops.agents.graph import build_graph
from relayops.agents.llm import ModelUnavailable
from relayops.core.clock import utcnow
from relayops.core.config import get_settings
from relayops.core.db import psycopg_dsn, session_scope
from relayops.models import InvestigationRun, Job
from relayops.services import actions, runs

log = logging.getLogger("relayops.worker")


@contextmanager
def run_lock(run_id: str):  # type: ignore[no-untyped-def]
    conn = psycopg.connect(psycopg_dsn(), autocommit=True)
    try:
        got = conn.execute("select pg_try_advisory_lock(hashtext(%s))", (run_id,)).fetchone()
        yield bool(got and got[0])
    finally:
        conn.close()  # closing the session releases the advisory lock


class Heartbeat(threading.Thread):
    def __init__(self, job_id: str, worker_id: str, lease: int) -> None:
        super().__init__(daemon=True)
        self.job_id, self.worker_id, self.lease = job_id, worker_id, lease
        self.stop_event = threading.Event()
        self.lost = False

    def run(self) -> None:
        while not self.stop_event.wait(max(1.0, self.lease / 3)):
            if not runs.heartbeat(self.job_id, self.worker_id, self.lease):
                self.lost = True
                return


_graph: Any = None


def graph() -> Any:
    global _graph
    if _graph is None:
        _graph = build_graph(get_checkpointer())
    return _graph


def _fail_run(run_id: str, message: str, kind: str = "run_failed") -> None:
    with session_scope() as db:
        run = db.get(InvestigationRun, run_id)
        assert run is not None
        run.error = message
    runs.emit(run_id, kind, None, {"error": message}, status="failed")


def execute_job(job_id: str, run_id: str, kind: str, payload: dict[str, Any], thread_id: str) -> str:
    """Advance the run's graph. Returns the final job status."""
    config = {"configurable": {"thread_id": thread_id}}
    g = graph()
    try:
        if kind == "resume":
            g.invoke(Command(resume=payload), config, durability="sync")
        else:
            snap = g.get_state(config)
            if snap.next == ("review",) or (snap.values and not snap.next):
                return "done"  # already paused for review or finished; nothing to advance
            g.invoke(None if snap.next else {"run_id": run_id}, config, durability="sync")
        return "done"
    except runs.RunCancelled:
        runs.emit(
            run_id,
            "run_cancelled",
            None,
            {"note": "Stopped before further model, tool, or action work."},
            status="cancelled",
        )
        return "cancelled"
    except runs.DeadlineExceeded:
        _fail_run(run_id, "run deadline exceeded")
        return "failed"
    except ModelUnavailable as exc:
        _fail_run(run_id, f"model unavailable: {exc}", "model_unavailable")
        return "failed"


def process_one(worker_id: str) -> bool:
    s = get_settings()
    with session_scope() as db:
        job = runs.claim_job(db, worker_id, s.job_lease_seconds)
        if job is None:
            return False
        job_id, run_id, kind, payload, attempts, max_attempts = (
            job.id,
            job.run_id,
            job.kind,
            dict(job.payload),
            job.attempts,
            job.max_attempts,
        )
        run = db.get(InvestigationRun, run_id)
        assert run is not None
        thread_id, cancelled = run.thread_id, run.status == "cancelled"
    if cancelled:
        runs.finish_job(job_id, worker_id, "cancelled")
        return True
    with run_lock(run_id) as locked:
        if not locked:
            # Another process is advancing this run; release the job for later.
            with session_scope() as db:
                j = db.get(Job, job_id)
                if j is not None and j.lease_owner == worker_id:
                    j.status, j.lease_owner, j.lease_expires_at = "queued", None, None
                    j.available_at = utcnow()
            time.sleep(0.5)
            return True
        hb = Heartbeat(job_id, worker_id, s.job_lease_seconds)
        hb.start()
        try:
            status = execute_job(job_id, run_id, kind, payload, thread_id)
            runs.finish_job(job_id, worker_id, status)
        except Exception as exc:  # unexpected failure: retry with backoff, then fail visibly
            log.exception("job %s failed", job_id)
            if attempts < max_attempts:
                with session_scope() as db:
                    j = db.get(Job, job_id)
                    if j is not None:
                        j.status, j.lease_owner, j.last_error = "queued", None, repr(exc)[:500]
                        j.available_at = utcnow()
            else:
                runs.finish_job(job_id, worker_id, "failed", repr(exc)[:500])
                _fail_run(run_id, f"worker error: {exc.__class__.__name__}")
        finally:
            hb.stop_event.set()
    with session_scope() as db:
        actions.deliver_outbox(db)
    return True


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    from relayops.core.instance import require_mode

    with session_scope() as db:
        mode = require_mode(db)
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    log.info("worker %s started (mode=%s, provider=%s)", worker_id, mode, get_settings().llm_provider)
    while not stop.is_set():
        try:
            if not process_one(worker_id):
                with session_scope() as db:
                    actions.deliver_outbox(db)  # retries (e.g. an unknown external outcome) also run when idle
                stop.wait(get_settings().worker_poll_seconds)
        except Exception:
            log.exception("worker loop error")
            stop.wait(2)
    log.info("worker %s stopped", worker_id)


if __name__ == "__main__":
    main()
