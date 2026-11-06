"""Investigation runs: creation, durable jobs, sequenced events, cancellation, and recorded replay."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from relayops.agents.llm import get_provider
from relayops.agents.prompts import prompt_hash
from relayops.core.clock import utcnow
from relayops.core.config import get_settings
from relayops.core.db import session_scope
from relayops.domain.playbooks import PlaybookConfig, choose_default_playbook
from relayops.domain.policies import POLICY_VERSION
from relayops.domain.scope import Conflict, Principal, ValidationFailed
from relayops.models import InvestigationRun, Job, Playbook, PlaybookRevision, RunEvent, TicketMessage, new_id
from relayops.repositories import scoped
from relayops.services import audit

ACTIVE = ("queued", "running", "awaiting_review", "executing")
TERMINAL = ("completed", "failed", "cancelled", "rejected")


class RunCancelled(Exception):
    pass


class DeadlineExceeded(Exception):
    pass


def playbook_config(db: Session, organization_id: str, key: str) -> tuple[Playbook, PlaybookRevision]:
    pb = db.execute(
        select(Playbook).where(Playbook.organization_id == organization_id, Playbook.key == key)
    ).scalar_one_or_none()
    if pb is None:
        raise ValidationFailed(f"unknown playbook '{key}'")
    rev = db.execute(
        select(PlaybookRevision).where(
            PlaybookRevision.playbook_id == pb.id, PlaybookRevision.revision == pb.current_revision
        )
    ).scalar_one()
    return pb, rev


def start_run(
    db: Session,
    p: Principal,
    ticket_id: str,
    *,
    playbook_key: str | None = None,
    retrieval_mode: str | None = None,
    compare_of_run_id: str | None = None,
    as_of: datetime | None = None,
) -> InvestigationRun:
    """`as_of` pins the evidence clock (evaluation and replay of historical cases); the API never sets it."""
    scoped.require_staff(p)
    ticket = scoped.get_ticket(db, p, ticket_id, for_update=True)
    if ticket.is_historical:
        raise ValidationFailed("historical tickets are reference data and cannot be investigated")
    active = db.execute(
        scoped.runs(p).where(
            InvestigationRun.ticket_id == ticket.id,
            InvestigationRun.status.in_(("queued", "running", "executing")),
            InvestigationRun.mode == "live",
        )
    ).first()
    if active:
        raise Conflict("an investigation for this ticket is already running")
    first_msg = (
        db.execute(
            select(TicketMessage.body).where(TicketMessage.ticket_id == ticket.id).order_by(TicketMessage.created_at)
        )
        .scalars()
        .first()
        or ""
    )
    key = playbook_key or choose_default_playbook(error_code=ticket.error_code, subject=ticket.subject, body=first_msg)
    _, rev = playbook_config(db, p.organization_id, key)
    cfg = PlaybookConfig.model_validate(rev.config)
    if retrieval_mode:
        if retrieval_mode not in ("lexical", "dense", "rrf"):
            raise ValidationFailed("unknown retrieval mode")
        cfg = cfg.model_copy(update={"retrieval_mode": retrieval_mode})
    s = get_settings()
    provider = get_provider()
    run_id = new_id("run")
    budgets = {
        "max_turns": min(cfg.max_turns, s.max_investigation_turns),
        "max_tool_calls": min(cfg.max_tool_calls, s.max_tool_calls),
        "max_repairs": s.max_repair_attempts,
        "deadline_seconds": s.run_deadline_seconds,
        "max_output_tokens": s.max_output_tokens,
        "num_ctx": s.num_ctx,
    }
    run = InvestigationRun(
        id=run_id,
        organization_id=p.organization_id,
        customer_account_id=ticket.customer_account_id,
        ticket_id=ticket.id,
        playbook_key=key,
        playbook_revision=rev.revision,
        thread_id=f"thread_{run_id}",
        mode="live",
        compare_of_run_id=compare_of_run_id,
        status="queued",
        ticket_revision=ticket.revision,
        model_provider=provider.name,
        model_name=provider.chat_model,
        model_digest=provider.model_digest(),
        prompt_hash=prompt_hash(cfg.model_dump(mode="json")),
        policy_version=POLICY_VERSION,
        retrieval_config={
            "mode": cfg.retrieval_mode,
            "k": s.tool_result_limit,
            "embed_model": provider.embed_model,
            "lexical_engine": "postgres ts_rank_cd",
        },
        budgets={**budgets, "playbook": cfg.model_dump(mode="json"), **({"as_of": as_of.isoformat()} if as_of else {})},
        usage={"turns": 0, "tool_calls": 0, "model_calls": 0, "repairs": 0},
        created_by_user_id=p.user_id,
    )
    db.add(run)
    db.flush()
    db.add(
        Job(organization_id=p.organization_id, run_id=run.id, kind="investigate", dedupe_key=f"investigate:{run.id}")
    )
    if ticket.status == "open":
        ticket.status = "pending_review"
    audit.record(
        db,
        organization_id=p.organization_id,
        actor=p,
        action="investigation.started",
        target_type="run",
        target_id=run.id,
        detail={"ticket": ticket.id, "playbook": key, "compare_of": compare_of_run_id},
    )
    _emit(db, run, "run_queued", None, {"playbook": key, "playbook_revision": rev.revision, "budgets": budgets})
    return run


def _emit(db: Session, run: InvestigationRun, kind: str, node: str | None, payload: dict[str, Any]) -> RunEvent:
    seq = (
        db.execute(
            update(InvestigationRun)
            .where(InvestigationRun.id == run.id)
            .values(next_seq=InvestigationRun.next_seq + 1)
            .returning(InvestigationRun.next_seq)
        ).scalar_one()
        - 1
    )
    ev = RunEvent(run_id=run.id, organization_id=run.organization_id, seq=seq, kind=kind, node=node, payload=payload)
    db.add(ev)
    db.flush()
    return ev


def emit(
    run_id: str,
    kind: str,
    node: str | None = None,
    payload: dict[str, Any] | None = None,
    *,
    status: str | None = None,
    current_node: str | None = None,
    usage: dict[str, Any] | None = None,
) -> None:
    """Append one event in its own short transaction (never spans inference)."""
    with session_scope() as db:
        run = db.get(InvestigationRun, run_id)
        assert run is not None
        _emit(db, run, kind, node, payload or {})
        if status:
            run.status = status
            if status in TERMINAL:
                run.finished_at = utcnow()
        if current_node is not None:
            run.current_node = current_node
        if usage is not None:
            run.usage = usage


def check_alive(run_id: str, *, deadline: bool = True) -> None:
    with session_scope() as db:
        run = db.get(InvestigationRun, run_id)
        assert run is not None
        if run.cancel_requested_at is not None or run.status == "cancelled":
            raise RunCancelled()
        if deadline and run.started_at is not None:
            limit = float(run.budgets.get("deadline_seconds", 420))
            if (utcnow() - run.started_at).total_seconds() > limit:
                raise DeadlineExceeded()


def remaining_seconds(run_id: str) -> float:
    with session_scope() as db:
        run = db.get(InvestigationRun, run_id)
        assert run is not None and run.started_at is not None
        return float(run.budgets.get("deadline_seconds", 420)) - (utcnow() - run.started_at).total_seconds()


def cancel_run(db: Session, p: Principal, run_id: str) -> InvestigationRun:
    scoped.require_staff(p)
    run = db.execute(scoped.runs(p).where(InvestigationRun.id == run_id).with_for_update()).scalar_one_or_none()
    if run is None:
        raise scoped.NotFound("investigation not found")
    if run.status in TERMINAL:
        raise Conflict(f"run already {run.status}")
    run.cancel_requested_at = utcnow()
    completed_effects = db.execute(
        text("select count(*) from action_ledger where run_id = :r and status in ('succeeded','unknown')"),
        {"r": run.id},
    ).scalar_one()
    if run.status in ("queued", "awaiting_review"):
        run.status = "cancelled"
        run.finished_at = utcnow()
    db.execute(update(Job).where(Job.run_id == run.id, Job.status == "queued").values(status="cancelled"))
    _emit(
        db,
        run,
        "cancel_requested",
        None,
        {
            "by": p.user_id,
            "note": "Future model, tool, and action work stops. Completed effects are not undone.",
            "completed_effects": int(completed_effects),
        },
    )
    audit.record(
        db,
        organization_id=p.organization_id,
        actor=p,
        action="investigation.cancelled",
        target_type="run",
        target_id=run.id,
        detail={"completed_effects": int(completed_effects)},
    )
    return run


def retry_run(db: Session, p: Principal, run_id: str) -> InvestigationRun:
    """Resume a failed run from its last durable checkpoint on the same thread."""
    scoped.require_staff(p)
    run = scoped.get_run(db, p, run_id)
    if run.status != "failed" or run.mode != "live":
        raise Conflict("only failed live runs can be retried")
    attempt = db.execute(text("select count(*) from jobs where run_id=:r"), {"r": run.id}).scalar_one()
    run.status = "queued"
    run.error = None
    run.finished_at = None
    run.started_at = utcnow()  # a retried attempt gets a fresh deadline window
    db.add(
        Job(
            organization_id=run.organization_id,
            run_id=run.id,
            kind="investigate",
            dedupe_key=f"investigate:{run.id}:retry{attempt}",
        )
    )
    _emit(db, run, "retry_requested", None, {"by": p.user_id})
    audit.record(
        db,
        organization_id=p.organization_id,
        actor=p,
        action="investigation.retried",
        target_type="run",
        target_id=run.id,
    )
    return run


def events_since(db: Session, p: Principal, run_id: str, after_seq: int = 0, limit: int = 500) -> list[RunEvent]:
    run = scoped.get_run(db, p, run_id)
    return list(
        db.execute(
            select(RunEvent)
            .where(RunEvent.run_id == run.id, RunEvent.seq > after_seq)
            .order_by(RunEvent.seq)
            .limit(limit)
        ).scalars()
    )


def recorded_replay(db: Session, p: Principal, run_id: str) -> InvestigationRun:
    """Re-present a finished run's recorded events. No model calls, no tools, and no actions execute."""
    scoped.require_staff(p)
    src = scoped.get_run(db, p, run_id)
    if src.mode != "live":
        raise ValidationFailed("replay a live run, not a replay")
    if src.status in ("queued", "running", "executing"):
        raise Conflict("wait for the run to stop before replaying it")
    rid = new_id("run")
    replay = InvestigationRun(
        id=rid,
        organization_id=src.organization_id,
        customer_account_id=src.customer_account_id,
        ticket_id=src.ticket_id,
        playbook_key=src.playbook_key,
        playbook_revision=src.playbook_revision,
        thread_id=f"replay_{rid}",
        mode="recorded_replay",
        replay_of_run_id=src.id,
        status="completed",
        ticket_revision=src.ticket_revision,
        route=src.route,
        verdict=src.verdict,
        model_provider="recorded",
        model_name=src.model_name,
        model_digest=src.model_digest,
        prompt_hash=src.prompt_hash,
        policy_version=src.policy_version,
        retrieval_config=src.retrieval_config,
        budgets=src.budgets,
        usage=src.usage,
        created_by_user_id=p.user_id,
        started_at=utcnow(),
        finished_at=utcnow(),
    )
    db.add(replay)
    db.flush()
    _emit(db, replay, "replay_started", None, {"source_run": src.id, "label": "RECORDED REPLAY: no effects execute"})
    for ev in db.execute(select(RunEvent).where(RunEvent.run_id == src.id).order_by(RunEvent.seq)).scalars():
        _emit(
            db,
            replay,
            ev.kind,
            ev.node,
            {**ev.payload, "replayed_from_seq": ev.seq, "recorded_at": ev.created_at.isoformat()},
        )
    _emit(db, replay, "replay_finished", None, {"source_run": src.id, "effects_executed": 0})
    audit.record(
        db,
        organization_id=p.organization_id,
        actor=p,
        action="investigation.replayed",
        target_type="run",
        target_id=replay.id,
        detail={"source": src.id},
    )
    return replay


def claim_job(db: Session, worker_id: str, lease_seconds: int) -> Job | None:
    """Claim one available job: queued, or leased with an expired lease (crash recovery)."""
    now = utcnow()
    job = db.execute(
        select(Job)
        .where(
            ((Job.status == "queued") & (Job.available_at <= now))
            | ((Job.status == "leased") & (Job.lease_expires_at < now))
        )
        .order_by(Job.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    ).scalar_one_or_none()
    if job is None:
        return None
    job.status = "leased"
    job.lease_owner = worker_id
    job.lease_expires_at = now + timedelta(seconds=lease_seconds)
    job.heartbeat_at = now
    job.attempts += 1
    return job


def heartbeat(job_id: str, worker_id: str, lease_seconds: int) -> bool:
    with session_scope() as db:
        n = db.execute(
            update(Job)
            .where(Job.id == job_id, Job.lease_owner == worker_id, Job.status == "leased")
            .values(heartbeat_at=utcnow(), lease_expires_at=utcnow() + timedelta(seconds=lease_seconds))
        ).rowcount  # type: ignore[attr-defined]
        return bool(n)


def finish_job(job_id: str, worker_id: str, status: str, error: str | None = None) -> None:
    with session_scope() as db:
        db.execute(
            update(Job)
            .where(Job.id == job_id, Job.lease_owner == worker_id)
            .values(status=status, last_error=error, finished_at=utcnow(), lease_expires_at=None)
        )
