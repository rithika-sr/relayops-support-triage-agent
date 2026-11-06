"""Trusted request principal. Built only from server-side sessions/tokens and membership rows."""

from __future__ import annotations

from dataclasses import dataclass, field

STAFF_ROLES = frozenset({"admin", "support"})


@dataclass(frozen=True)
class Principal:
    user_id: str
    email: str
    name: str
    membership_id: str
    organization_id: str
    role: str
    customer_account_id: str | None
    via: str = "session"  # session | api_token
    scopes: frozenset[str] = field(default_factory=frozenset)

    @property
    def is_staff(self) -> bool:
        return self.role in STAFF_ROLES

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def __post_init__(self) -> None:
        if self.role == "customer" and not self.customer_account_id:
            raise ValueError("customer principal requires a customer account")
        if self.role not in {"admin", "support", "customer"}:
            raise ValueError(f"unknown role {self.role}")


class AccessDenied(Exception):
    """Raised for authorization failures. API maps it to 404 for object reads to avoid ID probing."""


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


class ValidationFailed(Exception):
    pass
