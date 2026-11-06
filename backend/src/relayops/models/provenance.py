"""Instance data mode, ingestion batches, connections, and ingestion receipts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from relayops.models.base import Base, Tz, created_at_column, id_column

DATA_CLASSES = ("operational", "demo", "test", "unknown")
SOURCE_KINDS = ("portal", "manual", "import", "connector", "seed", "unknown")


class InstanceMetadata(Base):
    """Single row recording which data mode this database was initialized for."""

    __tablename__ = "instance_metadata"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    data_mode: Mapped[str] = mapped_column(String(16))  # operational | demo | test
    initialized_at: Mapped[datetime] = created_at_column()
    note: Mapped[str | None] = mapped_column(Text)


class ImportBatch(Base):
    __tablename__ = "import_batches"
    id: Mapped[str] = id_column("imp")
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    filename: Mapped[str] = mapped_column(String(255))
    content_sha256: Mapped[str] = mapped_column(String(64))
    format: Mapped[str] = mapped_column(String(8))  # csv | json
    status: Mapped[str] = mapped_column(String(16))  # committed | failed
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = created_at_column()


class Connection(Base):
    """A configured integration. Scope mapping lives here, server-side, never in request bodies."""

    __tablename__ = "connections"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)
    id: Mapped[str] = id_column("con")
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    kind: Mapped[str] = mapped_column(String(24))  # inbound_webhook | github_issues
    name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(16), default="configured")  # configured|healthy|degraded|disconnected
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    secret_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    last_success_at: Mapped[datetime | None] = mapped_column(Tz)
    last_error: Mapped[str | None] = mapped_column(Text)
    last_error_at: Mapped[datetime | None] = mapped_column(Tz)
    created_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = created_at_column()


class IngestionReceipt(Base):
    __tablename__ = "ingestion_receipts"
    __table_args__ = (UniqueConstraint("connection_id", "external_event_id"),)
    id: Mapped[str] = id_column("rcp")
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    connection_id: Mapped[str] = mapped_column(ForeignKey("connections.id"), index=True)
    external_event_id: Mapped[str] = mapped_column(String(160))
    payload_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))  # accepted | duplicate | rejected
    reason: Mapped[str | None] = mapped_column(Text)
    ticket_id: Mapped[str | None] = mapped_column(ForeignKey("tickets.id"))
    source_event_at: Mapped[datetime | None] = mapped_column(Tz)
    received_at: Mapped[datetime] = created_at_column()
