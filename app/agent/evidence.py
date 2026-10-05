from __future__ import annotations

import re
from typing import Any

_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_MAX_QUOTE_WORDS = 25
_MIN_SPAN_CHARS = 8
_MAX_SPANS = 24


def build_evidence_spans(pages: dict[int, str]) -> list[dict[str, Any]]:
    """Derive exact citable spans from fetched pages (no extra tool cost)."""
    spans: list[dict[str, Any]] = []
    for page in sorted(pages):
        text = (pages.get(page) or "").strip()
        if not text:
            continue
        for chunk in _SENT_SPLIT_RE.split(text):
            chunk = " ".join(chunk.split()).strip()
            if len(chunk) < _MIN_SPAN_CHARS:
                continue
            for piece in _chunk_words(chunk, _MAX_QUOTE_WORDS):
                if len(piece) < _MIN_SPAN_CHARS:
                    continue
                spans.append(
                    {
                        "id": f"E{len(spans) + 1}",
                        "page": int(page),
                        "text": piece,
                    }
                )
                if len(spans) >= _MAX_SPANS:
                    return spans
    return spans


def resolve_quote_refs(
    quotes_raw: list[Any],
    spans_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Map model quote objects to exact {page, text} using evidence ids when present."""
    quotes: list[dict[str, Any]] = []
    for q in quotes_raw:
        if not isinstance(q, dict):
            continue
        eid = str(q.get("id") or q.get("evidence_id") or "").strip().upper()
        if eid and eid in spans_by_id:
            span = spans_by_id[eid]
            quotes.append({"text": span["text"], "page": span["page"], "id": eid})
            continue
        text = str(q.get("text") or "").strip()
        try:
            page = int(q.get("page"))
        except (TypeError, ValueError):
            continue
        if text:
            item: dict[str, Any] = {"text": text, "page": page}
            if eid:
                item["id"] = eid
            quotes.append(item)
    return quotes


def _chunk_words(text: str, max_words: int) -> list[str]:
    words = text.split()
    if len(words) <= max_words:
        return [text]
    out: list[str] = []
    for i in range(0, len(words), max_words):
        piece = " ".join(words[i : i + max_words]).strip()
        if piece:
            out.append(piece)
    return out
