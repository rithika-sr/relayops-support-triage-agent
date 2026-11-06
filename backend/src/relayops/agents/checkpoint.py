"""LangGraph's supported Postgres checkpointer. We do not reimplement its schema."""

from __future__ import annotations

from functools import lru_cache

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from relayops.core.db import psycopg_dsn


def ensure_checkpointer_schema() -> None:
    with PostgresSaver.from_conn_string(psycopg_dsn()) as saver:
        saver.setup()


@lru_cache
def get_checkpointer() -> PostgresSaver:
    pool = ConnectionPool(
        psycopg_dsn(),
        min_size=1,
        max_size=4,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=True,
    )
    return PostgresSaver(pool)  # type: ignore[arg-type]
