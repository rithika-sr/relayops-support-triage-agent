"""Versioned service calendars. A version is never edited; changes create the next version."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from relayops.models.base import Base, created_at_column, id_column


class ServiceCalendarVersion(Base):
    __tablename__ = "service_calendar_versions"
    __table_args__ = (UniqueConstraint("organization_id", "name", "version"),)
    id: Mapped[str] = id_column("cal")
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    version: Mapped[int] = mapped_column(Integer)
    timezone: Mapped[str] = mapped_column(String(64))
    weekly: Mapped[dict[str, Any]] = mapped_column(JSON)
    holidays: Mapped[list[str]] = mapped_column(JSON, default=list)
    applies_to_urgent: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at_column()
