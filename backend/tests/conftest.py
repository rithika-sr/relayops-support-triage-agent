"""Test harness: a dedicated Postgres database, migrated once, truncated between tests.

Offline tests use the labeled FixtureProvider. Live Ollama checks live in tests/live and are opt-in.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

_BASE = os.environ.get("RELAYOPS_DATABASE_URL") or ""
if not _BASE:
    from relayops.core.config import Settings

    _BASE = Settings().database_url
TEST_URL = _BASE.rsplit("/", 1)[0] + "/relayops_test"
os.environ["RELAYOPS_DATABASE_URL"] = TEST_URL
os.environ["RELAYOPS_ENV"] = "test"
os.environ.setdefault("RELAYOPS_LLM_PROVIDER", "fixture")
os.environ.setdefault("RELAYOPS_SESSION_SECRET", "test-session-secret-0123456789")

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from relayops.agents import llm  # noqa: E402
from relayops.core.config import get_settings  # noqa: E402
from relayops.core.db import get_engine, new_session  # noqa: E402
from relayops.models import Base  # noqa: E402

get_settings.cache_clear()


def _ensure_database() -> None:
    admin = create_engine(_BASE.rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        if not c.execute(text("select 1 from pg_database where datname='relayops_test'")).first():
            c.execute(text("create database relayops_test"))
    admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def _migrated() -> Iterator[None]:
    _ensure_database()
    cfg = Config(str(os.path.join(os.path.dirname(__file__), "..", "alembic.ini")))
    command.upgrade(cfg, "head")
    from relayops.agents.checkpoint import ensure_checkpointer_schema

    ensure_checkpointer_schema()
    yield


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with get_engine().begin() as c:
        c.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        c.execute(
            text(
                "DO $$ BEGIN IF to_regclass('checkpoints') IS NOT NULL THEN "
                "TRUNCATE checkpoints, checkpoint_blobs, checkpoint_writes; END IF; END $$"
            )
        )
    fixture = llm.FixtureProvider()
    llm.set_provider(fixture)
    yield
    llm.set_provider(None)


@pytest.fixture
def db() -> Iterator[Session]:
    s = new_session()
    try:
        yield s
        s.commit()
    finally:
        s.close()


@pytest.fixture
def fixture_provider() -> llm.FixtureProvider:
    p = llm.get_provider()
    assert isinstance(p, llm.FixtureProvider)
    return p
