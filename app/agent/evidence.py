"""Evidence spans are built only after get_page, never during ingest.

Ids are stable for a given set of fetched pages: pages are walked in order
and each page gets at most 8 spans so a long early page cannot use every id.
"""

from __future__ import annotations

import re
from typing import Any

from app.agent.verifier import fragment_of_span, near_span

_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_MAX_QUOTE_WORDS = 45
_MAX_CODE_QUOTE_WORDS = 120
_MIN_SPAN_CHARS = 8
_MAX_SPANS_PER_PAGE = 8
_MAX_SPANS = 32
_SNAP_MIN = 90

_CODE_LINE_RE = re.compile(
    r"(^\s{2,})"
    r"|[{};#]"
    r"|->"
    r"|::"
    r"|</?\w"
    r"|=\s*[\"']"
    r"|\b("
    r"def|class|return|include|printf|scanf|fopen|fclose|malloc|free|"
    r"int|void|char|float|double|main|import|from|function|const|var|let|"
    r"public|private|static|nullptr|NULL|stdin|stdout|csv|json"
    r")\b",
    re.I,
)


def looks_like_code(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if _CODE_LINE_RE.search(t):
        return True
    if t.count("(") >= 1 and t.count(")") >= 1 and ("=" in t or ";" in t):
        return True
    return False


def span_genre(text: str) -> str:
    """Label a span so the answer call can prefer the right kind of line."""
    if looks_like_code(text):
        return "code"
    low = (text or "").lower()
    if any(k in low for k in ("supersed", "amend", "replaces", "replaced by", "in lieu")):
        return "amendment"
    if re.search(r"\b(is defined|defined as|means|refers to|definition of)\b", low):
        return "definition"
    if re.search(r"\b(step\s+\d|procedure|shall|must)\b", low):
        return "procedure"
    if re.search(r"\d", text or ""):
        return "quantity"
    return "prose"


def build_evidence_spans(pages: dict[int, str]) -> list[dict[str, Any]]:
    """Citable spans from pages already fetched. No tool cost and no model call."""
    spans: list[dict[str, Any]] = []
    for page in sorted(pages):
        text = (pages.get(page) or "").strip()
        if not text:
            continue
        page_count = 0
        for chunk in _iter_chunks(text):
            chunk = " ".join(chunk.split()).strip()
            if len(chunk) < _MIN_SPAN_CHARS:
                continue
            max_words = _MAX_CODE_QUOTE_WORDS if looks_like_code(chunk) else _MAX_QUOTE_WORDS
            for piece in _chunk_words(chunk, max_words):
                if len(piece) < _MIN_SPAN_CHARS:
                    continue
                spans.append(
                    {
                        "id": f"E{len(spans) + 1}",
                        "page": int(page),
                        "text": piece,
                        "genre": span_genre(piece),
                    }
                )
                page_count += 1
                if page_count >= _MAX_SPANS_PER_PAGE or len(spans) >= _MAX_SPANS:
                    break
            if page_count >= _MAX_SPANS_PER_PAGE or len(spans) >= _MAX_SPANS:
                break
        if len(spans) >= _MAX_SPANS:
            break
    return spans


def _snap_to_span(
    text: str,
    page: int,
    spans_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    if len(" ".join((text or "").split())) < _MIN_SPAN_CHARS:
        return None
    on_page = [s for s in spans_by_id.values() if int(s.get("page") or 0) == page]
    containing = [s for s in on_page if fragment_of_span(text, str(s.get("text") or ""))]
    if containing:
        return min(containing, key=lambda s: len(str(s.get("text") or "")))
    close = [s for s in on_page if near_span(text, str(s.get("text") or ""), minimum=_SNAP_MIN)]
    if not close:
        return None
    return min(close, key=lambda s: len(str(s.get("text") or "")))


def resolve_quote_refs(
    quotes_raw: list[Any],
    spans_by_id: dict[str, dict[str, Any]],
    pages: dict[int, str] | None = None,
) -> list[dict[str, Any]]:
    """Keep known span ids. Unknown ids are dropped. Free text must snap to a span."""
    del pages
    quotes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for q in quotes_raw:
        if not isinstance(q, dict):
            continue
        eid = str(q.get("id") or q.get("evidence_id") or "").strip().upper()
        if eid:
            span = spans_by_id.get(eid)
            if span is None or eid in seen:
                continue
            seen.add(eid)
            quotes.append({"text": span["text"], "page": int(span["page"]), "id": eid})
            continue
        text = str(q.get("text") or "").strip()
        try:
            page = int(q.get("page"))
        except (TypeError, ValueError):
            continue
        span = _snap_to_span(text, page, spans_by_id)
        if span is None:
            continue
        sid = str(span["id"]).upper()
        if sid in seen:
            continue
        seen.add(sid)
        quotes.append({"text": span["text"], "page": int(span["page"]), "id": sid})
    return quotes


def _iter_chunks(text: str) -> list[str]:
    out: list[str] = []
    prose_buf: list[str] = []

    def flush_prose() -> None:
        if not prose_buf:
            return
        block = "\n".join(prose_buf)
        prose_buf.clear()
        for chunk in _SENT_SPLIT_RE.split(block):
            c = chunk.strip()
            if c:
                out.append(c)

    for line in text.splitlines():
        raw = line.rstrip()
        if looks_like_code(raw):
            flush_prose()
            stripped = raw.strip()
            if stripped:
                out.append(stripped)
        else:
            prose_buf.append(raw)
    flush_prose()
    if not out and text.strip():
        out.extend(c.strip() for c in _SENT_SPLIT_RE.split(text) if c.strip())
    return out


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
