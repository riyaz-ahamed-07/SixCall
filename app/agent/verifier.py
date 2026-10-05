from __future__ import annotations

import re
from typing import Any

from app.textutil import normalize_text

_WS_RE = re.compile(r"\s+")
MIN_QUOTE_CHARS = 8

_CODEISH_RE = re.compile(
    r"[{};#]|->|::|</?\w|\b(def|class|return|include|printf|scanf|int|void|main|import)\b",
    re.I,
)


def _norm_for_match(text: str) -> str:
    """Narrow normalization for exact span checks (whitespace/Unicode only)."""
    text = normalize_text(text or "")
    text = _WS_RE.sub(" ", text).strip().lower()
    return text


def _is_word_char(ch: str) -> bool:
    # Treat alnum and common token glue as "inside a word" so
    # "eligible" cannot match inside "ineligible".
    return ch.isalnum() or ch in {"_", "*", "∗"}


def _looks_like_code_quote(text: str) -> bool:
    return bool(_CODEISH_RE.search(text or ""))


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


def quote_matches_page(quote: str, page_text: str) -> bool:
    """True if quote is an exact contiguous span of the page (code-aware)."""
    text = (quote or "").strip()
    if not text or text in {".", "...", "…"}:
        return False
    q_norm = _norm_for_match(text)
    if len(q_norm) < MIN_QUOTE_CHARS:
        return False
    p_norm = _norm_for_match(page_text or "")
    if not p_norm:
        return False
    # Code lines often sit mid-token after PDF glue; accept contiguous match.
    if _looks_like_code_quote(text):
        return q_norm in p_norm
    return _has_bounded_span(p_norm, q_norm)


def verify_quotes(
    quotes: list[dict[str, Any]],
    pages: dict[int, str],
    *,
    min_chars: int | None = None,
    allowed_ids: set[str] | None = None,
    span_texts: dict[str, str] | None = None,
) -> tuple[bool, list[str]]:
    """Accept an evidence id only when its text is that span, else an exact page span.

    The id must belong to a span built from a fetched page, and the quote text
    must be that span. Free-text quotes still need an exact contiguous span.
    """
    failures: list[str] = []
    if not quotes:
        return False, ["no quotes provided"]
    floor = MIN_QUOTE_CHARS if min_chars is None else max(1, int(min_chars))
    allowed = {str(i).upper() for i in allowed_ids} if allowed_ids else None
    spans = (
        {str(k).upper(): v for k, v in span_texts.items()} if span_texts else {}
    )

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
        eid = str(q.get("id") or q.get("evidence_id") or "").strip().upper()
        if allowed is not None and eid and eid in allowed:
            expected = spans.get(eid)
            if expected is not None and _norm_for_match(text) == _norm_for_match(expected):
                continue
            if expected is not None:
                failures.append(f"evidence id {eid} does not match its span text")
                continue
        if not text:
            failures.append("empty quote")
            continue
        if text in {".", "...", "…"}:
            failures.append("degenerate quote")
            continue
        q_norm = _norm_for_match(text)
        if len(q_norm) < floor:
            failures.append(f"quote too short on page {page_i} (min {floor} chars)")
            continue
        p_norm = _norm_for_match(source)
        if _looks_like_code_quote(text):
            if q_norm not in p_norm:
                failures.append(f"quote not found as contiguous span on page {page_i}")
            continue
        if not _has_bounded_span(p_norm, q_norm):
            failures.append(f"quote not found as bounded span on page {page_i}")

    return (len(failures) == 0, failures)
