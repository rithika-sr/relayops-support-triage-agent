from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from relayops.models.base import Base, Tz, created_at_column, id_column


class Ticket(Base):
    __tablename__ = "tickets"
    __table_args__ = (
        UniqueConstraint("organization_id", "number"),
        UniqueConstraint("organization_id", "external_event_id"),
    )
    id: Mapped[str] = id_column("tkt")
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    customer_account_id: Mapped[str] = mapped_column(ForeignKey("customer_accounts.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    subject: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(32), default="open")
    priority: Mapped[str] = mapped_column(String(16), default="normal")
    reported_severity: Mapped[str] = mapped_column(String(16), default="normal")
    component: Mapped[str | None] = mapped_column(String(64))
    product_version: Mapped[str | None] = mapped_column(String(32))
    error_code: Mapped[str | None] = mapped_column(String(80))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    restricted: Mapped[bool] = mapped_column(Boolean, default=False)
    is_historical: Mapped[bool] = mapped_column(Boolean, default=False)
    resolution_summary: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    external_event_id: Mapped[str | None] = mapped_column(String(120))
    # Provenance: derived server-side from the channel and the instance mode, never from client input.
    data_class: Mapped[str] = mapped_column(String(16), default="unknown", server_default="unknown", index=True)
    source_kind: Mapped[str] = mapped_column(String(16), default="unknown", server_default="unknown")
    source_system: Mapped[str | None] = mapped_column(String(120))
    source_connection_id: Mapped[str | None] = mapped_column(ForeignKey("connections.id"))
    import_batch_id: Mapped[str | None] = mapped_column(ForeignKey("import_batches.id"))
    source_event_at: Mapped[datetime | None] = mapped_column(Tz)
    received_at: Mapped[datetime | None] = mapped_column(Tz)
    created_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = created_at_column()
    first_response_due_at: Mapped[datetime | None] = mapped_column(Tz)
    first_responded_at: Mapped[datetime | None] = mapped_column(Tz)
    resolved_at: Mapped[datetime | None] = mapped_column(Tz)
    target_policy: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class TicketMessage(Base):
    __tablename__ = "ticket_messages"
    id: Mapped[str] = id_column("msg")
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    customer_account_id: Mapped[str] = mapped_column(ForeignKey("customer_accounts.id"))
    author_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    author_kind: Mapped[str] = mapped_column(String(16))  # customer | staff | system
    visibility: Mapped[str] = mapped_column(String(16))  # customer | internal
    body: Mapped[str] = mapped_column(Text)
    action_id: Mapped[str | None] = mapped_column(String(64))
    data_class: Mapped[str] = mapped_column(String(16), default="unknown", server_default="unknown", index=True)
    source_kind: Mapped[str] = mapped_column(String(16), default="unknown", server_default="unknown")
    created_at: Mapped[datetime] = created_at_column()
