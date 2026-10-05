from __future__ import annotations

import re
from typing import Any

from app.textutil import normalize_text

_WS_RE = re.compile(r"\s+")
MIN_QUOTE_CHARS = 8


def _norm_for_match(text: str) -> str:
    """Narrow normalization for exact span checks (whitespace/Unicode only)."""
    text = normalize_text(text or "")
    text = _WS_RE.sub(" ", text).strip().lower()
    return text


def _is_word_char(ch: str) -> bool:
    # Treat alnum and common token glue as "inside a word" so
    # "eligible" cannot match inside "ineligible".
    return ch.isalnum() or ch in {"_", "*", "∗"}


def _has_bounded_span(haystack: str, needle: str) -> bool:
    """True if needle occurs as a contiguous span with non-word edges."""
    if not needle or not haystack:
        return False
    start = 0
    while True:
        i = haystack.find(needle, start)
        if i < 0:
            return False
        before_ok = i == 0 or not _is_word_char(haystack[i - 1])
        end = i + len(needle)
        after_ok = end >= len(haystack) or not _is_word_char(haystack[end])
        if before_ok and after_ok:
            return True
        start = i + 1


def verify_quotes(
    quotes: list[dict[str, Any]], pages: dict[int, str]
) -> tuple[bool, list[str]]:
    """Every quote must be an exact contiguous word-bounded span of a fetched page."""
    failures: list[str] = []
    if not quotes:
        return False, ["no quotes provided"]

    for q in quotes:
        text = str(q.get("text") or "").strip()
        page = q.get("page")
        try:
            page_i = int(page)
        except (TypeError, ValueError):
            failures.append(f"invalid page for quote: {page!r}")
            continue
        source = pages.get(page_i)
        if source is None:
            failures.append(f"quote page {page_i} was not fetched")
            continue
        if not text:
            failures.append("empty quote")
            continue
        if text in {".", "...", "…"}:
            failures.append("degenerate quote")
            continue
        q_norm = _norm_for_match(text)
        if len(q_norm) < MIN_QUOTE_CHARS:
            failures.append(f"quote too short on page {page_i} (min {MIN_QUOTE_CHARS} chars)")
            continue
        p_norm = _norm_for_match(source)
        if not _has_bounded_span(p_norm, q_norm):
            failures.append(f"quote not found as bounded span on page {page_i}")

    return (len(failures) == 0, failures)
