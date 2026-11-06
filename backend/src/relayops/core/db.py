"""SQLAlchemy engine and session lifecycle."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from relayops.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True, pool_size=10, max_overflow=10)


@lru_cache
def _factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def new_session() -> Session:
    return _factory()()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Short transaction: commit on success, roll back on error. Never wrap inference in this."""
    db = new_session()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def psycopg_dsn() -> str:
    """Plain libpq DSN for the LangGraph checkpointer, which uses psycopg directly."""
    return get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")
