"""Fail-closed quote check. No model call.

An evidence id must name a span built from a fetched page. A retyped quote
is kept only when it is that span, an exact fragment of it, or rapidfuzz ≥90
with the same numbers and the same negation words.
"""

from __future__ import annotations

import re
from typing import Any

from app.textutil import normalize_text

_WS_RE = re.compile(r"\s+")
MIN_QUOTE_CHARS = 8
_SNAP_MIN = 90

_CODEISH_RE = re.compile(
    r"[{};#]|->|::|</?\w|\b(def|class|return|include|printf|scanf|int|void|main|import)\b",
    re.I,
)
_DIGIT_RE = re.compile(r"\d+")
_NEGATION_RE = re.compile(
    r"\b(?:not|no|never|none|without|cannot|can't|dont|don't|doesnt|doesn't)\b",
    re.I,
)


def _norm_for_match(text: str) -> str:
    text = normalize_text(text or "")
    text = _WS_RE.sub(" ", text).strip().lower()
    return text


def _is_word_char(ch: str) -> bool:
    return ch.isalnum() or ch in {"_", "*", "∗"}


def _looks_like_code_quote(text: str) -> bool:
    return bool(_CODEISH_RE.search(text or ""))


def _has_bounded_span(haystack: str, needle: str) -> bool:
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
    text = (quote or "").strip()
    if not text or text in {".", "...", "…"}:
        return False
    q_norm = _norm_for_match(text)
    if len(q_norm) < MIN_QUOTE_CHARS:
        return False
    p_norm = _norm_for_match(page_text or "")
    if not p_norm:
        return False
    if _looks_like_code_quote(text):
        return q_norm in p_norm
    return _has_bounded_span(p_norm, q_norm)


def _fuzz_ratio(left: str, right: str) -> int:
    from rapidfuzz.fuzz import ratio

    return int(ratio(left, right))


def _digits(text: str) -> tuple[str, ...]:
    return tuple(_DIGIT_RE.findall(_norm_for_match(text)))


def _negations(text: str) -> tuple[str, ...]:
    found = []
    for match in _NEGATION_RE.finditer(_norm_for_match(text)):
        token = match.group(0).replace("'", "")
        if token in {"dont", "doesnt"}:
            token = "not"
        found.append(token)
    return tuple(found)


def near_span(quote: str, span_text: str, *, minimum: int = _SNAP_MIN) -> bool:
    """Exact span, or high string similarity with the same numbers and negations."""
    if not quote or not span_text:
        return False
    if _norm_for_match(quote) == _norm_for_match(span_text):
        return True
    if _digits(quote) != _digits(span_text):
        return False
    if _negations(quote) != _negations(span_text):
        return False
    return _fuzz_ratio(_norm_for_match(quote), _norm_for_match(span_text)) >= minimum


def fragment_of_span(quote: str, span_text: str) -> bool:
    """Quote is a bounded piece of the span and adds no new number or negation."""
    q_norm = _norm_for_match(quote)
    s_norm = _norm_for_match(span_text)
    if not q_norm or not s_norm:
        return False
    if q_norm != s_norm and not _has_bounded_span(s_norm, q_norm):
        return False
    if set(_digits(quote)) - set(_digits(span_text)):
        return False
    if set(_negations(quote)) - set(_negations(span_text)):
        return False
    return True


def verify_quotes(
    quotes: list[dict[str, Any]],
    pages: dict[int, str],
    *,
    min_chars: int | None = None,
    allowed_ids: set[str] | None = None,
    span_texts: dict[str, str] | None = None,
    spans: list[dict[str, Any]] | None = None,
) -> tuple[bool, list[str]]:
    """Fail closed. Unknown evidence ids are rejected. This never calls a model."""
    failures: list[str] = []
    if not quotes:
        return False, ["no quotes provided"]
    floor = MIN_QUOTE_CHARS if min_chars is None else max(1, int(min_chars))
    allowed = {str(i).upper() for i in allowed_ids} if allowed_ids is not None else None
    texts = {str(k).upper(): v for k, v in span_texts.items()} if span_texts else {}
    by_page: dict[int, list[str]] = {}
    for span in spans or []:
        try:
            sp = int(span.get("page"))
        except (TypeError, ValueError):
            continue
        piece = str(span.get("text") or "")
        if piece:
            by_page.setdefault(sp, []).append(piece)

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
        if eid:
            page_mismatch = False
            for span in spans or []:
                if str(span.get("id") or "").upper() != eid:
                    continue
                try:
                    span_page = int(span.get("page"))
                except (TypeError, ValueError):
                    failures.append(f"evidence id {eid} has no page")
                    page_mismatch = True
                    break
                if span_page != page_i:
                    failures.append(f"evidence id {eid} is not on page {page_i}")
                    page_mismatch = True
                break
            if page_mismatch:
                continue
            known = (allowed is not None and eid in allowed) or (allowed is None and eid in texts)
            if allowed is not None and eid not in allowed:
                failures.append(f"unknown evidence id {eid}")
                continue
            if known:
                expected = texts.get(eid)
                if not text or (expected is not None and near_span(text, expected)):
                    continue
                if expected is not None:
                    failures.append(f"evidence id {eid} does not match its span text")
                    continue
                failures.append(f"evidence id {eid} has no span text")
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
            if q_norm in p_norm:
                continue
        elif _has_bounded_span(p_norm, q_norm):
            continue
        candidates = list(by_page.get(page_i) or [])
        if not candidates and texts:
            candidates = list(texts.values())
        if any(near_span(text, cand) for cand in candidates):
            continue
        failures.append(f"quote not found as bounded span on page {page_i}")

    return (len(failures) == 0, failures)
