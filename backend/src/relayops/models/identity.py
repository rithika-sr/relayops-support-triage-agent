from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from relayops.models.base import Base, Tz, created_at_column, id_column


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[str] = id_column("org")
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    data_class: Mapped[str] = mapped_column(String(16), default="unknown", server_default="unknown", index=True)
    created_at: Mapped[datetime] = created_at_column()


class CustomerAccount(Base):
    __tablename__ = "customer_accounts"
    id: Mapped[str] = id_column("acct")
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    plan: Mapped[str] = mapped_column(String(32))
    product_version: Mapped[str] = mapped_column(String(32))
    region: Mapped[str] = mapped_column(String(32), default="us")
    created_at: Mapped[datetime] = created_at_column()


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = id_column("usr")
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = created_at_column()


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "organization_id"),)
    id: Mapped[str] = id_column("mem")
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # admin | support | customer
    customer_account_id: Mapped[str | None] = mapped_column(ForeignKey("customer_accounts.id"))
    created_at: Mapped[datetime] = created_at_column()


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[str] = id_column("ses")
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    membership_id: Mapped[str] = mapped_column(ForeignKey("memberships.id"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = created_at_column()
    expires_at: Mapped[datetime] = mapped_column(Tz)
    revoked_at: Mapped[datetime | None] = mapped_column(Tz)
    last_seen_at: Mapped[datetime | None] = mapped_column(Tz)
    user_agent: Mapped[str | None] = mapped_column(String(300))


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    id: Mapped[str] = id_column("la")
    email: Mapped[str] = mapped_column(String(320), index=True)
    client_ip: Mapped[str] = mapped_column(String(64))
    success: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = created_at_column()


class Invitation(Base):
    __tablename__ = "invitations"
    id: Mapped[str] = id_column("inv")
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    customer_account_id: Mapped[str] = mapped_column(ForeignKey("customer_accounts.id"))
    email: Mapped[str] = mapped_column(String(320))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(Tz)
    accepted_at: Mapped[datetime | None] = mapped_column(Tz)
    created_at: Mapped[datetime] = created_at_column()


class ApiToken(Base):
    __tablename__ = "api_tokens"
    id: Mapped[str] = id_column("tok")
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    membership_id: Mapped[str] = mapped_column(ForeignKey("memberships.id"))
    name: Mapped[str] = mapped_column(String(120))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = created_at_column()
    revoked_at: Mapped[datetime | None] = mapped_column(Tz)
    last_used_at: Mapped[datetime | None] = mapped_column(Tz)
