"""Postgres connection helpers (Supabase)."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row

from app.config import DATABASE_URL, DB_CONNECT_TIMEOUT_SEC, DB_STATEMENT_TIMEOUT_MS

logger = logging.getLogger(__name__)


def db_enabled() -> bool:
    return bool(DATABASE_URL)


@contextmanager
def connect() -> Iterator[psycopg.Connection]:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set")
    with psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        connect_timeout=int(DB_CONNECT_TIMEOUT_SEC),
        options=f"-c statement_timeout={int(DB_STATEMENT_TIMEOUT_MS)}",
    ) as conn:
        yield conn


def migrate() -> None:
    """Explicit schema apply. Call via `python -m app.cli migrate` — not on API startup."""
    from app.db.schema import SCHEMA_SQL

    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set. Point it at the Supabase *dev* branch, then retry."
        )
    with connect() as conn:
        conn.execute(SCHEMA_SQL)
        conn.commit()
    logger.info("migrate_ok")
