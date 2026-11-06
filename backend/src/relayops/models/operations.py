"""Engineering issues, ownership, incidents, deployments, and synthetic error aggregates."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from relayops.models.base import Base, Tz, created_at_column, id_column


class EngineeringIssue(Base):
    __tablename__ = "engineering_issues"
    __table_args__ = (UniqueConstraint("organization_id", "key"),)
    id: Mapped[str] = id_column("iss")
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    key: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(16), default="bug")  # bug | feature
    component: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="open")  # open | investigating | fixed | wont_fix
    affected_versions: Mapped[list[str]] = mapped_column(JSON, default=list)
    fixed_in_version: Mapped[str | None] = mapped_column(String(32))
    error_signature: Mapped[str | None] = mapped_column(String(120))
    owner_team: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text, default="")
    origin: Mapped[str] = mapped_column(String(24), default="seed")  # seed | local_handoff
    origin_action_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = created_at_column()


class TicketIssueLink(Base):
    __tablename__ = "ticket_issue_links"
    __table_args__ = (UniqueConstraint("ticket_id", "issue_id"),)
    id: Mapped[str] = id_column("til")
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id"), index=True)
    issue_id: Mapped[str] = mapped_column(ForeignKey("engineering_issues.id"), index=True)
    link_kind: Mapped[str] = mapped_column(String(24))  # known_issue | handoff | feature_request
    action_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at_column()


class ComponentOwner(Base):
    __tablename__ = "component_owners"
    __table_args__ = (UniqueConstraint("organization_id", "component"),)
    id: Mapped[str] = id_column("own")
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    component: Mapped[str] = mapped_column(String(64))
    team: Mapped[str] = mapped_column(String(64))
    escalation: Mapped[str] = mapped_column(String(120))


class Deployment(Base):
    __tablename__ = "deployments"
    id: Mapped[str] = id_column("dep")
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    component: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(32))
    deployed_at: Mapped[datetime] = mapped_column(Tz)
    summary: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="succeeded")


class ErrorAggregate(Base):
    """Hourly synthetic error counts per account; staff-only diagnostic data."""

    __tablename__ = "error_aggregates"
    id: Mapped[str] = id_column("err")
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    customer_account_id: Mapped[str] = mapped_column(ForeignKey("customer_accounts.id"))
    component: Mapped[str] = mapped_column(String(64))
    error_signature: Mapped[str] = mapped_column(String(120))
    product_version: Mapped[str] = mapped_column(String(32))
    bucket_start: Mapped[datetime] = mapped_column(Tz, index=True)
    count: Mapped[int] = mapped_column(Integer)


class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[str] = id_column("inc")
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    component: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24))  # investigating | monitoring | resolved
    severity: Mapped[str] = mapped_column(String(8))
    started_at: Mapped[datetime] = mapped_column(Tz)
    resolved_at: Mapped[datetime | None] = mapped_column(Tz)
    error_signature: Mapped[str | None] = mapped_column(String(120))
    affected_versions: Mapped[list[str]] = mapped_column(JSON, default=list)
    internal_notes: Mapped[str] = mapped_column(Text, default="")
    public_summary: Mapped[str | None] = mapped_column(Text)
    public_visible: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmed_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_column()


class IncidentTicketLink(Base):
    __tablename__ = "incident_ticket_links"
    __table_args__ = (UniqueConstraint("incident_id", "ticket_id"),)
    id: Mapped[str] = id_column("itl")
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), index=True)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id"), index=True)
    linked_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    candidate_key: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at_column()
