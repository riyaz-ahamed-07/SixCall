"""Abstain text. The user-facing line is the fixed label; detail stays in `reason`."""

from __future__ import annotations

LABEL = "insufficient information"


def format_abstain_text(detail: str | None) -> tuple[str, str | None]:
    """Return (display text, support reason). Display text is only the label."""
    support = (detail or "").strip()
    if not support or support.lower() == LABEL:
        return LABEL, support or None
    return LABEL, support
