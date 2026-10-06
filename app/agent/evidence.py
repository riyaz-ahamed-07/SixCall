"""Evidence spans are built only after get_page, never during ingest.

Ids are stable for a given set of fetched pages: pages are walked in order
and each page gets at most 8 spans so a long early page cannot use every id.
Prose becomes sentence spans. A table row stays one span, digits included.
A code line stays one span, camelCase included.
"""

from __future__ import annotations

import re
from typing import Any

from app.agent.schemas import EvidenceSpan
from app.agent.verifier import fragment_of_span, near_span

_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_MAX_QUOTE_WORDS = 45
_MAX_CODE_QUOTE_WORDS = 120
_MIN_SPAN_CHARS = 8
_MAX_SPANS_PER_PAGE = 8
_MAX_SPANS = 32
_SNAP_MIN = 90
_SHORT_QUOTE_WORDS = 18

_TABLE_SPLIT_RE = re.compile(r"\S(?: {2,}|\t)\S(?: {2,}|\t)\S")
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


def looks_like_table_row(text: str) -> bool:
    line = text or ""
    if "\t" in line or line.count("|") >= 1:
        return True
    return bool(_TABLE_SPLIT_RE.search(line))


def span_genre(text: str, kind: str | None = None) -> str:
    """Label a span so the answer call can prefer the right kind of line."""
    if kind == "table":
        return "table"
    if kind == "code":
        return "code"
    if looks_like_table_row(text):
        return "table"
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
        for kind, chunk in _iter_chunks(text):
            # Collapse runs of space. camelCase and digits stay as written.
            chunk = " ".join(chunk.split()).strip()
            floor = 1 if kind in {"table", "code"} else _MIN_SPAN_CHARS
            if len(chunk) < floor:
                continue
            max_words = _MAX_CODE_QUOTE_WORDS if kind == "code" else _MAX_QUOTE_WORDS
            pieces = [chunk] if kind in {"table", "code"} else _chunk_words(chunk, max_words)
            for piece in pieces:
                if len(piece) < floor:
                    continue
                try:
                    span = EvidenceSpan(
                        id=f"E{len(spans) + 1}",
                        page=int(page),
                        text=piece,
                        genre=span_genre(piece, kind),
                    )
                except Exception:
                    continue
                spans.append(span.model_dump())
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


def _line_kind(line: str) -> str:
    raw = line or ""
    if not raw.strip():
        return "blank"
    if "\t" in raw or raw.count("|") >= 1:
        return "table"
    if looks_like_code(raw):
        return "code"
    if _TABLE_SPLIT_RE.search(raw):
        return "table"
    return "prose"


def _iter_chunks(text: str) -> list[tuple[str, str]]:
    """(kind, text) pairs. Kind is prose, table, or code. No ingest text is read."""
    out: list[tuple[str, str]] = []
    prose_buf: list[str] = []

    def flush_prose() -> None:
        if not prose_buf:
            return
        block = "\n".join(prose_buf)
        prose_buf.clear()
        for chunk in _SENT_SPLIT_RE.split(block):
            c = chunk.strip()
            if c:
                out.append(("prose", c))

    for line in text.splitlines():
        raw = line.rstrip()
        kind = _line_kind(raw)
        if kind == "blank":
            flush_prose()
            continue
        if kind == "prose":
            prose_buf.append(raw)
            continue
        flush_prose()
        stripped = raw.strip()
        if stripped:
            out.append((kind, stripped))
    flush_prose()
    if not out and text.strip():
        out.extend(("prose", c.strip()) for c in _SENT_SPLIT_RE.split(text) if c.strip())
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


def extend_quotes(
    quotes: list[dict[str, Any]],
    pages: dict[int, str],
) -> list[dict[str, Any]]:
    """Stretch short citations to the surrounding sentence when still on-page."""
    out: list[dict[str, Any]] = []
    for q in quotes:
        text = str(q.get("text") or "").strip()
        try:
            page = int(q.get("page"))
        except (TypeError, ValueError):
            continue
        source = pages.get(page) or ""
        if not text or not source:
            out.append(q)
            continue
        words = text.split()
        if len(words) >= _SHORT_QUOTE_WORDS or looks_like_code(text):
            out.append(q)
            continue
        extended = _expand_to_sentence(text, source)
        if extended and extended != text:
            item = dict(q)
            item["text"] = extended
            out.append(item)
        else:
            out.append(q)
    return out


def _expand_to_sentence(needle: str, page_text: str) -> str | None:
    from app.agent.verifier import _norm_for_match

    n = _norm_for_match(needle)
    if not n:
        return None
    candidates = [ln.strip() for ln in page_text.splitlines() if ln.strip()]
    candidates.extend(
        c.strip() for c in _SENT_SPLIT_RE.split(page_text) if c and c.strip()
    )
    best: str | None = None
    best_len = 0
    for cand in candidates:
        c_norm = _norm_for_match(cand)
        if n not in c_norm:
            continue
        words = cand.split()
        if len(words) < 2:
            continue
        max_w = (
            _MAX_CODE_QUOTE_WORDS if looks_like_code(cand) else _MAX_QUOTE_WORDS
        )
        if len(words) > max_w:
            piece = " ".join(words[:max_w])
            if _norm_for_match(needle) not in _norm_for_match(piece):
                n_words = needle.split()
                start = 0
                for i, w in enumerate(words):
                    if w.lower() == n_words[0].lower():
                        start = max(0, i - 4)
                        break
                piece = " ".join(words[start : start + max_w])
            cand = piece
            words = cand.split()
        if len(words) > best_len:
            best = cand
            best_len = len(words)
    return best


def repair_quotes(
    quotes: list[dict[str, Any]],
    pages: dict[int, str],
) -> list[dict[str, Any]]:
    """Replace unverifiable free-text quotes with overlapping evidence spans."""
    from app.agent.verifier import quote_matches_page

    spans = build_evidence_spans(pages)
    if not quotes and not spans:
        return []

    repaired: list[dict[str, Any]] = []
    for q in quotes or []:
        text = str(q.get("text") or "").strip()
        try:
            page = int(q.get("page"))
        except (TypeError, ValueError):
            continue
        source = pages.get(page)
        if source is None:
            continue
        if text and quote_matches_page(text, source):
            repaired.append(
                {"text": text, "page": page, **({"id": q["id"]} if q.get("id") else {})}
            )
            continue
        page_spans = [s for s in spans if int(s["page"]) == page]
        best = _best_overlap_span(text, page_spans)
        if best is None and looks_like_code(text):
            code_spans = [
                s for s in page_spans if looks_like_code(str(s.get("text") or ""))
            ]
            best = code_spans[0] if code_spans else None
        if best is not None:
            repaired.append(
                {"text": best["text"], "page": best["page"], "id": best["id"]}
            )

    if repaired:
        return repaired

    if not any(looks_like_code(str(q.get("text") or "")) for q in (quotes or [])):
        return []
    codeish = [s for s in spans if looks_like_code(str(s.get("text") or ""))]
    picked = codeish[:2]
    return [{"text": s["text"], "page": s["page"], "id": s["id"]} for s in picked]


def _best_overlap_span(
    needle: str, page_spans: list[dict[str, Any]]
) -> dict[str, Any] | None:
    from app.agent.verifier import _norm_for_match

    n = _norm_for_match(needle)
    if not n or not page_spans:
        return None
    best: dict[str, Any] | None = None
    best_score = 0
    for s in page_spans:
        t = _norm_for_match(str(s.get("text") or ""))
        if not t:
            continue
        if n in t or t in n:
            score = min(len(n), len(t))
            if score > best_score:
                best = s
                best_score = score
                continue
        n_toks = set(n.split())
        t_toks = set(t.split())
        if len(n_toks) < 2:
            continue
        overlap = len(n_toks & t_toks)
        if overlap >= max(2, len(n_toks) // 2) and overlap > best_score:
            best = s
            best_score = overlap
    return best
