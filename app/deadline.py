"""Request-scoped monotonic deadline for LLM / agent work."""

from __future__ import annotations

import time
from contextvars import ContextVar

_DEADLINE_MONO: ContextVar[float | None] = ContextVar("sixcall_deadline", default=None)


class DeadlineExceededError(TimeoutError):
    """Raised when the shared request deadline has elapsed."""


def start_deadline(seconds: float) -> None:
    _DEADLINE_MONO.set(time.monotonic() + max(0.1, float(seconds)))


def clear_deadline() -> None:
    _DEADLINE_MONO.set(None)


def deadline_remaining() -> float | None:
    end = _DEADLINE_MONO.get()
    if end is None:
        return None
    return max(0.0, end - time.monotonic())


def check_deadline() -> None:
    rem = deadline_remaining()
    if rem is not None and rem <= 0:
        raise DeadlineExceededError("request deadline exceeded")


def attempt_timeout(default: float = 20.0, *, floor: float = 1.0) -> float:
    """Per-call timeout bounded by remaining request time."""
    rem = deadline_remaining()
    if rem is None:
        return default
    return max(floor, min(default, rem))
