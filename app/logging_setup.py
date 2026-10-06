"""Console logging so every ingest / agent / API stage is visible under uvicorn."""

from __future__ import annotations

import logging
import os
import sys
import time
from typing import Any

_CONFIGURED = False


def configure_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    level_name = os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO"
    level = getattr(logging, level_name, logging.INFO)

    app_log = logging.getLogger("app")
    app_log.setLevel(level)
    app_log.handlers.clear()

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-5s | %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    # Flush each line so long PDF ingest stages appear while still running.
    handler.flush = sys.stderr.flush  # type: ignore[method-assign]
    app_log.addHandler(handler)
    app_log.propagate = False

    for noisy in (
        "LiteLLM",
        "litellm",
        "httpx",
        "httpcore",
        "openai",
        "uvicorn.access",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True
    app_log.info("logging ready level=%s", level_name)


def short(value: object, *, limit: int = 80) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _fmt_fields(fields: dict[str, Any]) -> str:
    if not fields:
        return ""
    parts: list[str] = []
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, float):
            if key.endswith("_ms") or key == "elapsed_ms":
                parts.append(f"{key}={value:.0f}")
            else:
                parts.append(f"{key}={value:.3f}")
        elif isinstance(value, str):
            parts.append(f"{key}={short(value, limit=100)}")
        else:
            parts.append(f"{key}={value}")
    return (" " + " ".join(parts)) if parts else ""


def step(phase: str, message: str, *args: Any, level: int = logging.INFO, **fields: Any) -> None:
    """Pipeline stage line: `[INGEST] parse_pages pages=613 (12400ms)`."""
    logger = logging.getLogger("app")
    tag = (phase or "APP").strip().upper()
    body = (message % args) if args else str(message)
    logger.log(level, "[%s] %s%s", tag, body, _fmt_fields(fields))


class StageTimer:
    """Time one named stage and log start + done/FAIL with elapsed_ms."""

    def __init__(self, phase: str, name: str, **fields: Any) -> None:
        self.phase = phase
        self.name = name
        self.fields = dict(fields)
        self._t0 = 0.0
        self._closed = False

    def __enter__(self) -> StageTimer:
        self._t0 = time.perf_counter()
        step(self.phase, f"{self.name} …", **self.fields)
        return self

    def detail(self, **fields: Any) -> None:
        self.fields.update(fields)

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._closed:
            return None
        self._closed = True
        elapsed_ms = (time.perf_counter() - self._t0) * 1000
        if exc is not None:
            err_name = type(exc).__name__ if exc else str(exc_type)
            step(
                self.phase,
                f"{self.name} FAIL",
                level=logging.ERROR,
                error=err_name,
                elapsed_ms=elapsed_ms,
                **self.fields,
            )
        else:
            step(self.phase, f"{self.name} ok", elapsed_ms=elapsed_ms, **self.fields)
        return None
