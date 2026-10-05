from __future__ import annotations

import re
from typing import Any

_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_MAX_QUOTE_WORDS = 45
_MAX_CODE_QUOTE_WORDS = 120
_MIN_SPAN_CHARS = 8
_MAX_SPANS = 40
_SHORT_QUOTE_WORDS = 18

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


def build_evidence_spans(pages: dict[int, str]) -> list[dict[str, Any]]:
    """Derive exact citable spans from fetched pages (no extra tool cost)."""
    spans: list[dict[str, Any]] = []
    for page in sorted(pages):
        text = (pages.get(page) or "").strip()
        if not text:
            continue
        for chunk in _iter_chunks(text):
            chunk = " ".join(chunk.split()).strip()
            if len(chunk) < _MIN_SPAN_CHARS:
                continue
            max_words = (
                _MAX_CODE_QUOTE_WORDS if looks_like_code(chunk) else _MAX_QUOTE_WORDS
            )
            for piece in _chunk_words(chunk, max_words):
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
    pages: dict[int, str] | None = None,
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
    if pages:
        quotes = extend_quotes(quotes, pages)
    return quotes


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
    # Prefer intact lines for code-ish pages; else sentence units.
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
            # Keep a window around the needle inside the long sentence.
            idx = c_norm.find(n)
            # Approximate by word overlap rather than char index on norm text.
            piece = " ".join(words[:max_w])
            if _norm_for_match(needle) not in _norm_for_match(piece):
                # Center window on first matching word of needle.
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
    """Replace unverifiable free-text quotes with overlapping evidence spans.

    Keeps the answer path alive for code/solution pages without inventing text.
    """
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
            repaired.append({"text": text, "page": page, **({"id": q["id"]} if q.get("id") else {})})
            continue
        page_spans = [s for s in spans if int(s["page"]) == page]
        best = _best_overlap_span(text, page_spans)
        if best is None and looks_like_code(text):
            code_spans = [s for s in page_spans if looks_like_code(str(s.get("text") or ""))]
            best = code_spans[0] if code_spans else None
        if best is not None:
            repaired.append(
                {"text": best["text"], "page": best["page"], "id": best["id"]}
            )

    if repaired:
        return repaired

    # Only fall back to code spans when the model was clearly citing code.
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
        # Token overlap for lightly paraphrased code comments / prompts.
        n_toks = set(n.split())
        t_toks = set(t.split())
        if len(n_toks) < 2:
            continue
        overlap = len(n_toks & t_toks)
        if overlap >= max(2, len(n_toks) // 2) and overlap > best_score:
            best = s
            best_score = overlap
    return best


def _iter_chunks(text: str) -> list[str]:
    """Prefer intact code lines; sentence-split prose only."""
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
