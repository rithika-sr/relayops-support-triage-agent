"""Product events (versioned schema, deduplicated) and experiments."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from relayops.models.base import Base, Tz, created_at_column, id_column


class ProductEvent(Base):
    __tablename__ = "product_events"
    __table_args__ = (
        UniqueConstraint("organization_id", "event_id"),
        Index("ix_product_events_org_name_time", "organization_id", "name", "occurred_at"),
    )
    id: Mapped[str] = id_column("evt")
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    customer_account_id: Mapped[str | None] = mapped_column(ForeignKey("customer_accounts.id"), index=True)
    event_id: Mapped[str] = mapped_column(String(160))  # dedupe key, unique per organization
    name: Mapped[str] = mapped_column(String(48))
    schema_version: Mapped[int] = mapped_column(Integer)
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    occurred_at: Mapped[datetime] = mapped_column(Tz)
    received_at: Mapped[datetime] = created_at_column()
    properties: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(12))  # app | import
    data_class: Mapped[str] = mapped_column(String(16), index=True)


class Experiment(Base):
    __tablename__ = "experiments"
    __table_args__ = (UniqueConstraint("organization_id", "key"),)
    id: Mapped[str] = id_column("exp")
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    key: Mapped[str] = mapped_column(String(60))
    hypothesis: Mapped[str] = mapped_column(Text)
    metric: Mapped[str] = mapped_column(String(48))
    variants: Mapped[list[str]] = mapped_column(JSON)
    min_accounts_per_variant: Mapped[int] = mapped_column(Integer, default=50)
    status: Mapped[str] = mapped_column(String(12), default="draft")  # draft | running | stopped
    started_at: Mapped[datetime | None] = mapped_column(Tz)
    stopped_at: Mapped[datetime | None] = mapped_column(Tz)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_column()
