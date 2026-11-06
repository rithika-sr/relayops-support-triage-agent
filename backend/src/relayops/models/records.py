"""Artifacts, playbooks, audit history, and evaluation reports."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from relayops.models.base import Base, created_at_column, id_column


class Artifact(Base):
    __tablename__ = "artifacts"
    id: Mapped[str] = id_column("art")
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    customer_account_id: Mapped[str | None] = mapped_column(ForeignKey("customer_accounts.id"))
    ticket_id: Mapped[str | None] = mapped_column(ForeignKey("tickets.id"))
    run_id: Mapped[str | None] = mapped_column(ForeignKey("investigation_runs.id"))
    proposal_id: Mapped[str | None] = mapped_column(ForeignKey("proposals.id"), unique=True)
    incident_id: Mapped[str | None] = mapped_column(ForeignKey("incidents.id"))
    kind: Mapped[str] = mapped_column(String(32))  # customer_reply | engineering_brief | incident_summary
    data_class: Mapped[str] = mapped_column(String(16), default="unknown", server_default="unknown", index=True)
    title: Mapped[str] = mapped_column(String(300))
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    review_status: Mapped[str] = mapped_column(String(24), default="draft")  # draft | approved | rejected
    created_at: Mapped[datetime] = created_at_column()


class ArtifactVersion(Base):
    __tablename__ = "artifact_versions"
    __table_args__ = (UniqueConstraint("artifact_id", "version"),)
    id: Mapped[str] = id_column("arv")
    artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    verification: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    verification_status: Mapped[str] = mapped_column(String(16))  # passed | failed | stale | unverified
    verified_content_hash: Mapped[str | None] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()


class Playbook(Base):
    __tablename__ = "playbooks"
    __table_args__ = (UniqueConstraint("organization_id", "key"),)
    id: Mapped[str] = id_column("pbk")
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    key: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text)
    current_revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = created_at_column()


class PlaybookRevision(Base):
    __tablename__ = "playbook_revisions"
    __table_args__ = (UniqueConstraint("playbook_id", "revision"),)
    id: Mapped[str] = id_column("pbr")
    playbook_id: Mapped[str] = mapped_column(ForeignKey("playbooks.id"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    revision: Mapped[int] = mapped_column(Integer)
    config: Mapped[dict[str, Any]] = mapped_column(JSON)
    config_hash: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at_column()


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = id_column("aud")
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    actor_kind: Mapped[str] = mapped_column(String(16))  # user | agent | system
    action: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(16), default="ok")  # ok | failed | unknown | denied
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = created_at_column()


class EvalReport(Base):
    __tablename__ = "eval_reports"
    __table_args__ = (UniqueConstraint("organization_id", "report_key"),)
    id: Mapped[str] = id_column("evr")
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    report_key: Mapped[str] = mapped_column(String(160))
    profile: Mapped[str] = mapped_column(String(40))
    report_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON)
    cases: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    source_path: Mapped[str] = mapped_column(String(300))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()
