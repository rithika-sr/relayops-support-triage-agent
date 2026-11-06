"""Investigation runs, events, durable jobs, proposals, reviews, and the action ledger/outbox."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, ForeignKey, Identity, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from relayops.models.base import Base, Tz, created_at_column, id_column


class InvestigationRun(Base):
    __tablename__ = "investigation_runs"
    id: Mapped[str] = id_column("run")
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    customer_account_id: Mapped[str] = mapped_column(ForeignKey("customer_accounts.id"))
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id"), index=True)
    playbook_key: Mapped[str] = mapped_column(String(32))
    playbook_revision: Mapped[int] = mapped_column(Integer)
    thread_id: Mapped[str] = mapped_column(String(80), unique=True)
    data_class: Mapped[str] = mapped_column(String(16), default="unknown", server_default="unknown", index=True)
    mode: Mapped[str] = mapped_column(String(24), default="live")  # live | recorded_replay
    replay_of_run_id: Mapped[str | None] = mapped_column(String(64))
    compare_of_run_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="queued")
    current_node: Mapped[str | None] = mapped_column(String(48))
    ticket_revision: Mapped[int] = mapped_column(Integer)
    route: Mapped[str | None] = mapped_column(String(40))
    verdict: Mapped[str | None] = mapped_column(String(40))
    model_provider: Mapped[str] = mapped_column(String(24))
    model_name: Mapped[str] = mapped_column(String(120))
    model_digest: Mapped[str | None] = mapped_column(String(80))
    prompt_hash: Mapped[str | None] = mapped_column(String(64))
    policy_version: Mapped[str] = mapped_column(String(32))
    retrieval_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    budgets: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    usage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_column()
    started_at: Mapped[datetime | None] = mapped_column(Tz)
    finished_at: Mapped[datetime | None] = mapped_column(Tz)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(Tz)
    next_seq: Mapped[int] = mapped_column(Integer, default=1)


class RunEvent(Base):
    __tablename__ = "run_events"
    __table_args__ = (UniqueConstraint("run_id", "seq"),)
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("investigation_runs.id"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    seq: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32))
    node: Mapped[str | None] = mapped_column(String(48))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = created_at_column()


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = id_column("job")
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    run_id: Mapped[str] = mapped_column(ForeignKey("investigation_runs.id"), index=True)
    kind: Mapped[str] = mapped_column(String(24))  # investigate | resume
    dedupe_key: Mapped[str] = mapped_column(String(160), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued | leased | done | failed | cancelled
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    lease_owner: Mapped[str | None] = mapped_column(String(80))
    lease_expires_at: Mapped[datetime | None] = mapped_column(Tz)
    heartbeat_at: Mapped[datetime | None] = mapped_column(Tz)
    available_at: Mapped[datetime] = created_at_column()
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()
    finished_at: Mapped[datetime | None] = mapped_column(Tz)


class Proposal(Base):
    __tablename__ = "proposals"
    __table_args__ = (UniqueConstraint("run_id", "version"),)
    id: Mapped[str] = id_column("prp")
    run_id: Mapped[str] = mapped_column(ForeignKey("investigation_runs.id"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    customer_account_id: Mapped[str] = mapped_column(ForeignKey("customer_accounts.id"))
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    route: Mapped[str] = mapped_column(String(40))
    action_kind: Mapped[str] = mapped_column(String(40))
    destination: Mapped[dict[str, Any]] = mapped_column(JSON)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64))
    data_class: Mapped[str] = mapped_column(String(16), default="unknown", server_default="unknown", index=True)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    evidence_hash: Mapped[str] = mapped_column(String(64))
    policy_version: Mapped[str] = mapped_column(String(32))
    ticket_revision: Mapped[int] = mapped_column(Integer)
    verification: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    verification_status: Mapped[str] = mapped_column(String(16))  # passed | failed | stale
    status: Mapped[str] = mapped_column(String(24), default="pending_review")
    authored_by: Mapped[str] = mapped_column(String(64))  # agent | usr_...
    created_at: Mapped[datetime] = created_at_column()


class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[str] = id_column("rev")
    proposal_id: Mapped[str] = mapped_column(ForeignKey("proposals.id"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    reviewer_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    decision: Mapped[str] = mapped_column(String(16))  # approve | reject
    binding: Mapped[dict[str, Any]] = mapped_column(JSON)
    binding_hash: Mapped[str] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()


class ActionRecord(Base):
    """Action ledger. `idempotency_key` is unique so one approval can produce at most one effect."""

    __tablename__ = "action_ledger"
    id: Mapped[str] = id_column("act")
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    customer_account_id: Mapped[str] = mapped_column(ForeignKey("customer_accounts.id"))
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("proposals.id"), unique=True)
    review_id: Mapped[str] = mapped_column(ForeignKey("reviews.id"))
    run_id: Mapped[str] = mapped_column(ForeignKey("investigation_runs.id"))
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id"))
    action_kind: Mapped[str] = mapped_column(String(40))
    adapter: Mapped[str] = mapped_column(String(32), default="local")
    data_class: Mapped[str] = mapped_column(String(16), default="unknown", server_default="unknown", index=False)

    destination: Mapped[dict[str, Any]] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))  # succeeded | failed | unknown | reconciled
    receipt: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = created_at_column()
    completed_at: Mapped[datetime | None] = mapped_column(Tz)


class OutboxMessage(Base):
    __tablename__ = "outbox"
    id: Mapped[str] = id_column("obx")
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    action_id: Mapped[str] = mapped_column(ForeignKey("action_ledger.id"), index=True)
    topic: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = created_at_column()
    delivered_at: Mapped[datetime | None] = mapped_column(Tz)
