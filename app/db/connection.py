"""Postgres connection helpers (Supabase)."""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row

from app.config import (
    DATABASE_URL,
    DB_CONNECT_TIMEOUT_SEC,
    DB_STATEMENT_TIMEOUT_MS,
    DB_WRITE_TIMEOUT_MS,
)
from app.logging_setup import step

logger = logging.getLogger(__name__)


def db_enabled() -> bool:
    return bool(DATABASE_URL)


@contextmanager
def connect(*, statement_timeout_ms: int | None = None) -> Iterator[psycopg.Connection]:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set")
    timeout = int(
        DB_STATEMENT_TIMEOUT_MS if statement_timeout_ms is None else statement_timeout_ms
    )
    t0 = time.perf_counter()
    try:
        with psycopg.connect(
            DATABASE_URL,
            row_factory=dict_row,
            connect_timeout=int(DB_CONNECT_TIMEOUT_SEC),
            options=f"-c statement_timeout={timeout}",
        ) as conn:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            # Fast connects are normal; only surface slow/hanging ones.
            if elapsed_ms >= 200:
                step(
                    "DB",
                    "connect slow",
                    elapsed_ms=elapsed_ms,
                    statement_timeout_ms=timeout,
                )
            yield conn
    except Exception as exc:
        step(
            "DB",
            "connect FAIL",
            level=logging.ERROR,
            error=type(exc).__name__,
            elapsed_ms=(time.perf_counter() - t0) * 1000,
        )
        raise


@contextmanager
def connect_write() -> Iterator[psycopg.Connection]:
    """Longer statement timeout for PDF ingest / bulk page writes."""
    with connect(statement_timeout_ms=max(DB_WRITE_TIMEOUT_MS, DB_STATEMENT_TIMEOUT_MS)) as conn:
        yield conn


def migrate() -> None:
    """Explicit schema apply. Call via `python -m app.cli migrate` — not on API startup."""
    from app.db.schema import SCHEMA_SQL

    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set. Point it at the Supabase *dev* branch, then retry."
        )
    with connect_write() as conn:
        conn.execute(SCHEMA_SQL)
        conn.commit()
    logger.info("migrate_ok")
