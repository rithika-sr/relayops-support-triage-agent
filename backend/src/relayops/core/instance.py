"""Instance data mode: operational, demo, or test. Enforced by server configuration and the database itself.

A database records the mode it was initialized for (`instance_metadata`). Processes refuse to start when the
configured mode does not match, so a demo configuration can never be pointed at an operational database (or the
reverse) by accident, and a browser toggle cannot relabel records.
"""

from __future__ import annotations

import sys

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from relayops.core.config import Settings, get_settings
from relayops.models import InstanceMetadata, Organization


class InstanceModeError(RuntimeError):
    pass


def validate_settings(s: Settings) -> None:
    if s.data_mode == "operational":
        if s.llm_provider != "ollama":
            raise InstanceModeError(
                "operational mode requires a real model provider; the fixture provider is test-only"
            )
        if s.session_secret.startswith("dev-only") or len(s.session_secret) < 32:
            raise InstanceModeError("operational mode requires a generated RELAYOPS_SESSION_SECRET (run make setup)")


def recorded_mode(db: Session) -> str | None:
    row = db.get(InstanceMetadata, 1)
    return row.data_mode if row else None


def initialize(db: Session, s: Settings | None = None) -> str:
    """Record the instance mode on first migration. Refuses to label seeded demo data as operational."""
    s = s or get_settings()
    existing = recorded_mode(db)
    if existing:
        if existing != s.data_mode:
            raise InstanceModeError(
                f"database was initialized for '{existing}' data but RELAYOPS_DATA_MODE is '{s.data_mode}'"
            )
        return existing
    demo_orgs = db.execute(select(func.count(Organization.id)).where(Organization.data_class == "demo")).scalar_one()
    if demo_orgs and s.data_mode == "operational":
        raise InstanceModeError(
            "this database contains demo-seeded organizations; run it with RELAYOPS_DATA_MODE=demo or point "
            "RELAYOPS_DATABASE_URL at a fresh database for operational use (see docs/operations.md)"
        )
    db.add(
        InstanceMetadata(
            id=1,
            data_mode=s.data_mode,
            note="initialized by migrate" + (" (legacy demo data detected)" if demo_orgs else ""),
        )
    )
    db.flush()
    return s.data_mode


def require_mode(db: Session, s: Settings | None = None) -> str:
    s = s or get_settings()
    validate_settings(s)
    mode = recorded_mode(db)
    if mode is None:
        raise InstanceModeError("database is not initialized; run make migrate")
    if mode != s.data_mode:
        raise InstanceModeError(f"database holds '{mode}' data but RELAYOPS_DATA_MODE is '{s.data_mode}'")
    return mode


def main() -> None:
    from relayops.core.db import session_scope

    try:
        with session_scope() as db:
            print(f"instance data mode: {initialize(db)}")
    except InstanceModeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
