from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import pymupdf as fitz

from app.config import DOC_STORE_DIR
from app.index.dual_index import build_precision_index, precision_lookup
from app.store.section_tree import lexical_heading_candidates
from app.textutil import (
    collapse_ws,
    keyword_aliases,
    needs_ocr,
    normalize_text,
    tokenize as _tokenize_base,
)

try:
    import snowballstemmer

    _STEMMER = snowballstemmer.stemmer("english")
except Exception:  # pragma: no cover - optional
    _STEMMER = None

logger = logging.getLogger(__name__)

_HEADING_NUM_RE = re.compile(r"^\d+(\.\d+)*\s+\S")
_HYPHEN_BREAK_RE = re.compile(r"([a-z])-\n([a-z])")
# Margin TOC often lands mid-line before a hyphen break, e.g.
# "contro- 1.1 Brief history of AI 1\nversial" — strip before dehyphenating.
_INLINE_TOC_RE = re.compile(
    r"\s+\d+(?:\.\d+)+\s+[A-Z?][^\n]{0,60}?\s+\d+(?=\s*\n)"
)
_WS_RE = re.compile(r"[ \t]+")
# Stamped WATERMARK debris only. Do not split or delete real words that merely
# contain "ate" (create, update, date, late) or the standalone word "ate".
_WATERMARK_GLUE_RE = re.compile(
    r"(?<=[A-Za-z])(?=(?:WATERMARK|WATERMAR|WATERMA|WATERM|ATERMARK|RMARK)\b)",
    re.I,
)
_WATERMARK_CRUMB_RE = re.compile(
    r"^(?:[WwAa]{1,4}|WATERM(?:ARK|A)?|ATERMARK|RMARK)$",
    re.I,
)
_STAMP_TOKEN_RE = re.compile(
    r"^(?:WATERMARK|WATERMAR|WATERMA|WATERM|ATERMARK|RMARK)$",
    re.I,
)
_STAMP_CRUMB_RE = re.compile(r"^(?:W|WA|WAT|A|K|E)$", re.I)
_JUNK_HEADING_RE = re.compile(
    r"^(?:field|value|team|theme|category|document type|product name|problem code|"
    r"a|w|wa|wat|ate|mark|watermark|waterm|atermark|rmark|"
    r"(?:[kwae\s]|ate|wat|rk|te){2,})$",
    re.I,
)
_MAX_HEADINGS_KEEP = 160


class DocumentStoreError(Exception):
    """Base error for document-store failures (safe for traces)."""


class UnknownDocumentError(KeyError, DocumentStoreError):
    """Raised when doc_id is missing or not ingested."""

    def __init__(self, doc_id: str) -> None:
        self.doc_id = doc_id
        super().__init__(f"unknown doc_id: {doc_id!r}")


class InvalidPageNumberError(ValueError, DocumentStoreError):
    """Raised when page_number is not a positive 1-based integer."""

    def __init__(self, page_number: object) -> None:
        self.page_number = page_number
        super().__init__(f"page_number must be >= 1, got {page_number!r}")


class PageNotFoundError(KeyError, DocumentStoreError):
    """Raised when a requested page is outside the ingested document."""

    def __init__(self, doc_id: str, page_number: int) -> None:
        self.doc_id = doc_id
        self.page_number = page_number
        super().__init__(f"page {page_number} not found in doc {doc_id!r}")


def _validate_page_number(page_number: object) -> int:
    if not isinstance(page_number, int) or isinstance(page_number, bool) or page_number < 1:
        raise InvalidPageNumberError(page_number)
    return page_number


@lru_cache(maxsize=32768)
def stem_token(token: str) -> str:
    t = normalize_text(token).lower()
    # Don't stem technical / symbolic tokens
    if any(ch in t for ch in "*+#/") or re.fullmatch(r"o\([a-z0-9+\-]+\)", t):
        return t
    if len(t) <= 3:
        return t
    if _STEMMER is None:
        return t
    stemmed = _STEMMER.stemWord(t)
    return stemmed or t


def tokenize(text: str) -> list[str]:
    return _tokenize_base(text)


def _is_watermark_crumb_line(stripped: str) -> bool:
    """Drop a line only when every token is stamp debris and there are at least two.

    A lone ``A`` (or any single content token) is kept.
    """
    tokens = [t.strip(" ,.;:") for t in stripped.split() if t.strip(" ,.;:")]
    if len(tokens) < 2:
        return False
    return all(_WATERMARK_CRUMB_RE.match(t) for t in tokens)


def scrub_watermark_noise(text: str) -> str:
    """Strip stamped WATERMARK fragments without deleting ordinary words."""
    if not text:
        return ""
    text = _WATERMARK_GLUE_RE.sub(" ", text)
    kept: list[str] = []
    for ln in text.split("\n"):
        stripped = ln.strip()
        if not stripped or _is_watermark_crumb_line(stripped):
            continue
        words = stripped.split()
        has_stamp = any(_STAMP_TOKEN_RE.match(w.strip(" ,.;:")) for w in words)
        if has_stamp:
            kept_words = []
            for w in words:
                core = w.strip(" ,.;:")
                if _STAMP_TOKEN_RE.match(core) or _STAMP_CRUMB_RE.match(core):
                    continue
                kept_words.append(w)
            cleaned = " ".join(kept_words).strip(" ,")
        else:
            cleaned = _WS_RE.sub(" ", stripped).strip(" ,")
        if cleaned:
            kept.append(cleaned)
    return "\n".join(kept)


def clean_page_text(raw: str) -> str:
    text = normalize_text(raw or "")
    text = scrub_watermark_noise(text)
    text = _INLINE_TOC_RE.sub("", text)
    text = _HYPHEN_BREAK_RE.sub(r"\1\2", text)
    return collapse_ws(text)


def _extract_flags() -> int:
    """Dissolve ligatures + dehyphenate line breaks (PyMuPDF known pitfalls)."""
    flags = getattr(fitz, "TEXTFLAGS_TEXT", 0)
    preserve = getattr(fitz, "TEXT_PRESERVE_LIGATURES", 0)
    if preserve:
        flags &= ~preserve
    dehyp = getattr(fitz, "TEXT_DEHYPHENATE", 0)
    if dehyp:
        flags |= dehyp
    return flags


def _extract_page_text(page: fitz.Page) -> str:
    flags = _extract_flags()
    try:
        text = page.get_text("text", sort=True, flags=flags) or ""
    except TypeError:
        text = page.get_text("text", sort=True) or ""
    text = clean_page_text(text)
    if needs_ocr(text):
        try:
            tp = page.get_textpage_ocr(language="eng", dpi=200, full=False)
            try:
                ocr_text = page.get_text("text", textpage=tp, sort=True, flags=flags) or ""
            except TypeError:
                ocr_text = page.get_text("text", textpage=tp, sort=True) or ""
            ocr_text = clean_page_text(ocr_text)
            if len(ocr_text) > len(text) and not needs_ocr(ocr_text, min_chars=5):
                text = ocr_text
            elif len(ocr_text) > len(text):
                text = ocr_text
        except Exception:
            pass
    return text


@dataclass
class Heading:
    title: str
    level: int
    start: int
    end: int


@dataclass
class DocRecord:
    doc_id: str
    meta: dict[str, Any]
    pages: dict[int, str]
    labels: dict[int, str]
    headings: list[Heading] = field(default_factory=list)
    index: dict[str, list[int]] = field(default_factory=dict)
    precision_index: dict[str, list[int]] = field(default_factory=dict)

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "meta": self.meta,
            "pages": {str(k): v for k, v in self.pages.items()},
            "labels": {str(k): v for k, v in self.labels.items()},
            "headings": [asdict(h) for h in self.headings],
            "index": self.index,
            "precision_index": self.precision_index,
        }

    @classmethod
    def from_jsonable(cls, data: dict[str, Any]) -> DocRecord:
        return cls(
            doc_id=data["doc_id"],
            meta=data["meta"],
            pages={int(k): v for k, v in data["pages"].items()},
            labels={int(k): v for k, v in data["labels"].items()},
            headings=[Heading(**h) for h in data.get("headings", [])],
            index={k: list(v) for k, v in data.get("index", {}).items()},
            precision_index={k: list(v) for k, v in data.get("precision_index", {}).items()},
        )


def _line_signature(line: str) -> str:
    return _WS_RE.sub(" ", line.strip().lower())


def remove_repeated_headers_footers(pages: dict[int, str]) -> dict[int, str]:
    if not pages:
        return pages
    top_counts: dict[str, int] = defaultdict(int)
    bottom_counts: dict[str, int] = defaultdict(int)
    page_lines: dict[int, list[str]] = {}

    for n, text in pages.items():
        lines = [ln for ln in text.split("\n") if ln.strip()]
        page_lines[n] = lines
        for ln in lines[:3]:
            sig = _line_signature(ln)
            if len(sig) >= 3:
                top_counts[sig] += 1
        for ln in lines[-3:]:
            sig = _line_signature(ln)
            if len(sig) >= 3:
                bottom_counts[sig] += 1

    if len(pages) == 1:
        return pages

    ban_top = {s for s, c in top_counts.items() if c > len(pages) * 0.5}
    ban_bottom = {s for s, c in bottom_counts.items() if c > len(pages) * 0.5}
    if not ban_top and not ban_bottom:
        return pages

    cleaned: dict[int, str] = {}
    for n, lines in page_lines.items():
        kept: list[str] = []
        for i, ln in enumerate(lines):
            sig = _line_signature(ln)
            if i < 3 and sig in ban_top:
                continue
            if i >= max(0, len(lines) - 3) and sig in ban_bottom:
                continue
            kept.append(ln)
        cleaned[n] = "\n".join(kept).strip()
    return cleaned


def _is_junk_heading_title(title: str) -> bool:
    t = (title or "").strip()
    if not t or len(t) < 3:
        return True
    if _JUNK_HEADING_RE.match(t):
        return True
    tl = t.lower()
    if any(x in tl for x in ("watermark", "waterm", "atermark")):
        return True
    words = t.split()
    if len(words) == 1 and len(t) <= 3:
        return True
    # Pure page numbers / bare section numbers with no title text
    if re.fullmatch(r"\d+(\.\d+)*", t):
        return True
    crumb = {"a", "w", "wa", "wat", "ate", "te", "rk", "k", "e"}
    crumb_n = sum(1 for w in words if w.lower() in crumb)
    if words and crumb_n / len(words) >= 0.5:
        return True
    return False


def _filter_headings(
    headings: list[Heading], *, page_count: int
) -> list[Heading]:
    """Drop watermark/table junk and collapse absurd heading floods."""
    cleaned: list[Heading] = []
    seen: set[tuple[int, str]] = set()
    for h in headings:
        title = clean_page_text(h.title)
        if _is_junk_heading_title(title):
            continue
        start = max(1, min(int(h.start or 1), max(1, page_count)))
        end = max(start, min(int(h.end or start), max(1, page_count)))
        key = (start, title.lower())
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(Heading(title=title, level=int(h.level or 1), start=start, end=end))

    if not cleaned:
        return []

    # If almost everything is pinned to page 1 on a long doc, keep numbered/title-like only.
    if page_count >= 8:
        on_first = sum(1 for h in cleaned if h.start == 1)
        if on_first / len(cleaned) >= 0.65:
            numbered = [h for h in cleaned if _HEADING_NUM_RE.match(h.title)]
            substantive = [h for h in cleaned if len(h.title.split()) >= 3]
            merged: list[Heading] = []
            seen_t: set[str] = set()
            for h in numbered + substantive:
                key = h.title.lower()
                if key in seen_t:
                    continue
                seen_t.add(key)
                merged.append(h)
            cleaned = merged or cleaned[: min(40, len(cleaned))]

    if len(cleaned) > _MAX_HEADINGS_KEEP:
        # Prefer earlier outline levels, then earlier pages.
        cleaned = sorted(
            cleaned,
            key=lambda h: (int(h.level or 99), int(h.start or 1), h.title.lower()),
        )[:_MAX_HEADINGS_KEEP]
        cleaned = sorted(cleaned, key=lambda h: (int(h.start or 1), int(h.level or 1)))
    return cleaned


def _headings_usable(headings: list[Heading], page_count: int) -> bool:
    if len(headings) < 2:
        return False
    if page_count >= 5 and len(headings) > max(80, page_count * 6):
        return False
    if page_count >= 8:
        on_first = sum(1 for h in headings if int(h.start or 1) == 1)
        if on_first / max(1, len(headings)) >= 0.75:
            return False
    junk = sum(1 for h in headings if _is_junk_heading_title(h.title))
    if junk / max(1, len(headings)) >= 0.4:
        return False
    return True


def _headings_from_toc(doc: fitz.Document, page_count: int) -> list[Heading]:
    toc = doc.get_toc(simple=True) or []
    if not toc:
        return []
    raw: list[tuple[int, str, int]] = []
    for level, title, page in toc:
        p = int(page)
        # PyMuPDF: page == -1 means no destination / outside document — skip.
        if p < 1:
            continue
        if p > page_count:
            p = page_count
        title = clean_page_text(str(title))
        if not title or _is_junk_heading_title(title):
            continue
        raw.append((int(level), title, p))
    if not raw:
        return []
    headings = _headings_with_hierarchy(raw, page_count)
    return _filter_headings(headings, page_count=page_count)


def _headings_with_hierarchy(
    raw: list[tuple[int, str, int]], page_count: int
) -> list[Heading]:
    """End a section at the next heading of equal or higher rank (not first child)."""
    headings: list[Heading] = []
    for i, (level, title, start) in enumerate(raw):
        end = page_count
        for j in range(i + 1, len(raw)):
            next_level, _, next_start = raw[j]
            if next_level <= level:
                end = max(start, next_start - 1)
                break
        headings.append(Heading(title=title, level=level, start=start, end=end))
    return headings


def _is_heading_candidate(text: str, size: float, flags: int, median_size: float) -> bool:
    t = text.strip()
    if not t or len(t) > 120:
        return False
    if _is_junk_heading_title(t):
        return False
    if t.endswith("."):
        return False
    words = t.split()
    if len(words) > 14:
        return False
    bold = bool(flags & 2**4)
    large = size >= median_size * 1.15
    numbered = bool(_HEADING_NUM_RE.match(t))
    if numbered:
        return True
    # Require real title shape — blocks "Field"/"Value"/watermark crumbs.
    if len(words) < 2:
        return False
    return (bold or large) and len(words) <= 12


def _headings_from_fonts(doc: fitz.Document) -> list[Heading]:
    sizes: list[float] = []
    candidates: list[tuple[int, str, float, int]] = []

    for page_index in range(doc.page_count):
        page = doc.load_page(page_index)
        data = page.get_text("dict", sort=True) or {}
        for block in data.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                if not spans:
                    continue
                text = "".join(s.get("text", "") for s in spans).strip()
                if not text:
                    continue
                size = max(float(s.get("size", 0)) for s in spans)
                flags = int(spans[0].get("flags", 0))
                sizes.append(size)
                candidates.append((page_index + 1, text, size, flags))

    if not candidates:
        return []

    sizes_sorted = sorted(sizes)
    median_size = sizes_sorted[len(sizes_sorted) // 2] if sizes_sorted else 11.0

    seen: set[tuple[int, str]] = set()
    raw: list[tuple[int, str, int]] = []
    for page_no, text, size, flags in candidates:
        text = clean_page_text(text)
        if not _is_heading_candidate(text, size, flags, median_size):
            continue
        key = (page_no, text.lower())
        if key in seen:
            continue
        seen.add(key)
        level = 1
        m = re.match(r"^(\d+(?:\.\d+)*)\s+", text)
        if m:
            level = m.group(1).count(".") + 1
        elif size >= median_size * 1.4:
            level = 1
        elif size >= median_size * 1.2:
            level = 2
        else:
            level = 3
        raw.append((level, text, page_no))

    if not raw:
        return []

    headings = _headings_with_hierarchy(raw, doc.page_count)
    return _filter_headings(headings, page_count=doc.page_count)


def _build_section_tree(
    doc: fitz.Document, pages: dict[int, str]
) -> tuple[list[Heading], str]:
    """TOC, then font size, then lexical heading lines."""
    page_count = doc.page_count
    toc_heads = _headings_from_toc(doc, page_count)
    if _headings_usable(toc_heads, page_count):
        return toc_heads, "toc"
    font_heads = _headings_from_fonts(doc)
    if _headings_usable(font_heads, page_count):
        return font_heads, "font"
    raw = lexical_heading_candidates(pages)
    lexical = _filter_headings(
        _headings_with_hierarchy(raw, page_count), page_count=page_count
    )
    if lexical:
        return lexical, "lexical"
    if font_heads:
        return _filter_headings(font_heads, page_count=page_count), "font"
    if toc_heads:
        return _filter_headings(toc_heads, page_count=page_count), "toc"
    return [], "none"


def build_inverted_index(pages: dict[int, str]) -> dict[str, list[int]]:
    index: dict[str, set[int]] = defaultdict(set)
    for page_no, text in pages.items():
        for tok in set(tokenize(text)):
            index[stem_token(tok)].add(page_no)
    return {k: sorted(v) for k, v in index.items()}


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    """Match phrase allowing common PDF glyph variants for * and spaces."""
    phrase = normalize_text(phrase.strip())
    parts: list[str] = []
    for ch in phrase:
        if ch == "*":
            parts.append(r"[*∗·]")
        elif ch == " ":
            parts.append(r"\s+")
        elif ch == "-":
            parts.append(r"[\-−–—]?")
        else:
            parts.append(re.escape(ch))
    return re.compile("".join(parts), re.IGNORECASE)


def _phrase_pages(pages: dict[int, str], phrase: str, candidate_pages: list[int]) -> list[int]:
    pattern = _phrase_pattern(phrase)
    hits: list[int] = []
    for p in candidate_pages:
        if pattern.search(normalize_text(pages.get(p, ""))):
            hits.append(p)
    return hits


def _scan_pages_for_pattern(pages: dict[int, str], phrase: str) -> list[int]:
    pattern = _phrase_pattern(phrase)
    return sorted(
        p for p, text in pages.items() if pattern.search(normalize_text(text))
    )


def _lookup_single(rec: DocRecord, keyword: str) -> list[int]:
    keyword = normalize_text((keyword or "").strip())
    if not keyword:
        return []

    tokens = tokenize(keyword)
    if not tokens:
        return _scan_pages_for_pattern(rec.pages, keyword)

    stems = [stem_token(t) for t in tokens]
    page_sets = [set(rec.index.get(s, [])) for s in stems]
    if not page_sets or any(len(s) == 0 for s in page_sets):
        # Symbolic / rare forms: fall back to page scan
        if any(any(ch in t for ch in "*+#") for t in tokens) or any(
            ch in keyword for ch in "*+#"
        ):
            return _scan_pages_for_pattern(rec.pages, keyword)
        # Also try scan for short technical tokens that stemming may miss
        if len(keyword) <= 12:
            scanned = _scan_pages_for_pattern(rec.pages, keyword)
            if scanned:
                return scanned
        return []

    candidates = sorted(set.intersection(*page_sets))
    if len(tokens) == 1:
        tok = tokens[0]
        if any(ch in tok for ch in "*+#"):
            return _phrase_pages(rec.pages, tok, candidates) or candidates
        return candidates
    return _phrase_pages(rec.pages, keyword, candidates)


class DocumentStore:
    def __init__(
        self, persist_dir: Path | None = None, *, use_db: bool | None = None
    ) -> None:
        self.persist_dir = Path(persist_dir or DOC_STORE_DIR)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        # Remote DB only for the default app store — never for test temp dirs.
        # SIXCALL_USE_DB=0 keeps the CLI demo on local JSON even if DATABASE_URL is set.
        if use_db is not None:
            self.use_db = bool(use_db)
        else:
            flag = os.getenv("SIXCALL_USE_DB", "auto").strip().lower()
            if flag in {"0", "false", "no", "off"}:
                self.use_db = False
            elif flag in {"1", "true", "yes", "on"}:
                self.use_db = True
            else:
                self.use_db = self.persist_dir.resolve() == Path(DOC_STORE_DIR).resolve()
        self._docs: dict[str, DocRecord] = {}
        self._load_all()

    def _path_for(self, doc_id: str) -> Path:
        return self.persist_dir / f"{doc_id}.json"

    def _pdf_path_for(self, doc_id: str) -> Path:
        return self.persist_dir / f"{doc_id}.pdf"

    def _save_pdf_bytes(self, doc_id: str, file_bytes: bytes) -> Path:
        path = self._pdf_path_for(doc_id)
        path.write_bytes(file_bytes)
        return path

    def pdf_file_path(self, doc_id: str) -> Path | None:
        """Return path to persisted original PDF if present."""
        path = self._pdf_path_for(doc_id)
        return path if path.is_file() and path.stat().st_size > 0 else None

    def _repair_record(self, rec: DocRecord) -> tuple[DocRecord, bool]:
        """Re-apply page cleaners + heading filters to older ingested caches."""
        before_h = len(rec.headings)
        before_chars = sum(len(t or "") for t in rec.pages.values())
        page_count = max(1, len(rec.pages) or int(rec.meta.get("page_count") or 1))
        rec.pages = {int(n): clean_page_text(t) for n, t in rec.pages.items()}
        rec.pages = remove_repeated_headers_footers(rec.pages)
        rec.headings = _filter_headings(
            [
                Heading(
                    title=clean_page_text(h.title),
                    level=h.level,
                    start=h.start,
                    end=h.end,
                )
                for h in rec.headings
            ],
            page_count=page_count,
        )
        rec.index = build_inverted_index(rec.pages)
        rec.precision_index = build_precision_index(rec.pages)
        after_chars = sum(len(t or "") for t in rec.pages.values())
        changed = len(rec.headings) != before_h or after_chars != before_chars
        return rec, changed

    def _load_all(self) -> None:
        loaded = 0
        if self.use_db:
            try:
                from app.db.connection import db_enabled
                from app.db.repository import load_all_documents

                if db_enabled():
                    for rec in load_all_documents():
                        rec, changed = self._repair_record(rec)
                        self._docs[rec.doc_id] = rec
                        if changed:
                            self._persist(rec)
                        loaded += 1
                    if loaded:
                        logger.info("store_loaded_db docs=%d", loaded)
                        return
            except Exception as exc:
                logger.warning("store_db_load_failed error=%s", type(exc).__name__)

        for path in sorted(self.persist_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                rec = DocRecord.from_jsonable(data)
                rec, changed = self._repair_record(rec)
                self._docs[rec.doc_id] = rec
                if changed:
                    self._persist(rec)
                loaded += 1
            except Exception as exc:
                logger.warning(
                    "skip_corrupt_store_file path=%s error=%s",
                    path.name,
                    type(exc).__name__,
                )
        if loaded:
            logger.info("store_loaded docs=%d dir=%s", loaded, self.persist_dir.name)

    def _persist(self, rec: DocRecord) -> None:
        path = self._path_for(rec.doc_id)
        path.write_text(
            json.dumps(rec.to_jsonable(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if not self.use_db:
            return
        try:
            from app.db.repository import save_document

            save_document(rec)
        except Exception as exc:
            logger.warning(
                "store_db_persist_failed doc_id=%s error=%s",
                rec.doc_id,
                type(exc).__name__,
            )

    def get(self, doc_id: str) -> DocRecord | None:
        """Return the in-memory record for doc_id, or None if missing."""
        return self._docs.get(doc_id)

    def list_documents(self, owner_id: str | None = None) -> list[dict[str, Any]]:
        """List ingested docs sorted by title (stable for demos/judges)."""
        out: list[dict[str, Any]] = []
        for rec in self._docs.values():
            if owner_id and owner_id != "local":
                if str(rec.meta.get("owner_id") or "") != str(owner_id):
                    continue
            out.append(
                {
                    "doc_id": rec.doc_id,
                    # Prefer the uploaded filename over PDF metadata / temp stems.
                    "title": rec.meta.get("source_name")
                    or rec.meta.get("title")
                    or rec.doc_id,
                    "page_count": rec.meta.get("page_count", len(rec.pages)),
                    "source_name": rec.meta.get("source_name"),
                    "filename": rec.meta.get("source_name"),
                    "owner_id": rec.meta.get("owner_id"),
                }
            )
        out.sort(key=lambda d: (str(d.get("title", "")), str(d.get("doc_id", ""))))
        return out

    def preview(
        self, doc_id: str, *, page_number: int = 1, heading_limit: int = 40
    ) -> dict[str, Any]:
        """UI preview payload (not an agent tool — does not use the call budget)."""
        rec = self._require(doc_id)
        page_number = _validate_page_number(page_number)
        if page_number not in rec.pages:
            raise PageNotFoundError(doc_id, page_number)
        headings = [
            {
                "title": h.title,
                "level": h.level,
                "start": h.start,
                "end": h.end,
            }
            for h in rec.headings[: max(0, heading_limit)]
        ]
        text = clean_page_text(rec.pages[page_number])
        # Cap preview body for fast modal loads.
        if len(text) > 4500:
            text = text[:4500].rstrip() + "…"
        return {
            "doc_id": rec.doc_id,
            "title": rec.meta.get("source_name")
            or rec.meta.get("title")
            or rec.doc_id,
            "source_name": rec.meta.get("source_name"),
            "page_count": int(rec.meta.get("page_count") or len(rec.pages)),
            "page_number": page_number,
            "page_text": text,
            "headings": headings,
        }

    def owned_by(self, doc_id: str, owner_id: str | None) -> bool:
        rec = self._docs.get(doc_id)
        if rec is None:
            return False
        if not owner_id or owner_id == "local":
            return True
        return str(rec.meta.get("owner_id") or "") == str(owner_id)

    def list_headings(self, doc_id: str) -> list[dict[str, Any]]:
        """Return outline headings for an ingested document.

        Each heading includes page_count so callers can sample without a store import.
        Docs with no TOC get a single synthetic span covering the whole document.
        """
        rec = self._require(doc_id)
        page_count = int(rec.meta.get("page_count") or len(rec.pages) or 1)
        if not rec.headings:
            return [
                {
                    "title": "(document)",
                    "level": 1,
                    "start": 1,
                    "end": page_count,
                    "page_count": page_count,
                }
            ]
        return [{**asdict(h), "page_count": page_count} for h in rec.headings]

    def get_page(self, doc_id: str, page_number: int) -> str:
        """Return cleaned text for a 1-based page_number.

        Raises:
            UnknownDocumentError: doc_id not ingested.
            InvalidPageNumberError: page_number < 1.
            PageNotFoundError: page exists as a number but not in this doc.
        """
        page_number = _validate_page_number(page_number)
        rec = self._require(doc_id)
        if page_number not in rec.pages:
            raise PageNotFoundError(doc_id, page_number)
        # Re-apply cleaner so older ingested pages pick up extractor fixes.
        return clean_page_text(rec.pages[page_number])

    def search_keyword(self, doc_id: str, keyword: str) -> list[int]:
        """Return sorted page numbers matching keyword (and known aliases).

        Empty or whitespace-only keyword returns []. Does not burn budget;
        the tool wrapper owns call counting.
        """
        rec = self._require(doc_id)
        keyword = (keyword or "").strip()
        if not keyword:
            return []

        aliases = keyword_aliases(keyword)
        precise: set[int] = set()
        for alias in aliases:
            hit = precision_lookup(rec.precision_index, alias)
            if hit:
                precise.update(int(p) for p in hit)
        if precise:
            return sorted(precise)
        hits: set[int] = set()
        for alias in aliases:
            for page in _lookup_single(rec, alias):
                hits.add(int(page))
        return sorted(hits)

    def _require(self, doc_id: str) -> DocRecord:
        if not (doc_id or "").strip():
            raise UnknownDocumentError(doc_id or "")
        rec = self._docs.get(doc_id)
        if rec is None:
            raise UnknownDocumentError(doc_id)
        return rec

    def ingest_pdf(self, path: str | Path, *, owner_id: str | None = None, source_name: str | None = None) -> str:
        """Parse a PDF into pages/headings/keyword map; return stable doc_id.

        Without owner: doc_id = sha256(file_bytes)[:16].
        With owner: doc_id = sha256(owner_id + ':' + file_bytes)[:16] so tenants isolate.
        Idempotent for the same owner + bytes.
        """
        pdf_path = Path(path).expanduser().resolve()
        if not pdf_path.exists():
            raise FileNotFoundError(str(pdf_path))
        if not pdf_path.is_file():
            raise FileNotFoundError(f"not a file: {pdf_path}")

        file_bytes = pdf_path.read_bytes()
        if owner_id and owner_id != "local":
            doc_id = hashlib.sha256(f"{owner_id}:".encode() + file_bytes).hexdigest()[:16]
        else:
            doc_id = hashlib.sha256(file_bytes).hexdigest()[:16]
        if doc_id in self._docs:
            rec = self._docs[doc_id]
            changed = False
            if owner_id and owner_id != "local":
                if rec.meta.get("owner_id") != owner_id:
                    rec.meta["owner_id"] = owner_id
                    changed = True
            if source_name and rec.meta.get("source_name") != source_name:
                rec.meta.update(source_name=source_name, title=Path(source_name).stem)
                rec.meta.pop("source_path", None)
                changed = True
            # Keep/restore original PDF bytes for real preview.
            self._save_pdf_bytes(doc_id, file_bytes)
            if changed:
                self._persist(rec)
            logger.info(
                "ingest_cached doc_id=%s source_name=%s",
                doc_id,
                pdf_path.name,
            )
            return doc_id

        with fitz.open(stream=file_bytes, filetype="pdf") as doc:
            pages: dict[int, str] = {}
            labels: dict[int, str] = {}
            for i in range(doc.page_count):
                page = doc.load_page(i)
                page_no = i + 1
                pages[page_no] = _extract_page_text(page)
                try:
                    labels[page_no] = str(page.get_label() or page_no)
                except Exception:
                    labels[page_no] = str(page_no)

            pages = remove_repeated_headers_footers(pages)
            pages = {n: clean_page_text(t) for n, t in pages.items()}

            headings, heading_source = _build_section_tree(doc, pages)
            index = build_inverted_index(pages)
            precision_index = build_precision_index(pages)

            meta_title = (doc.metadata or {}).get("title") or ""
            meta = {
                "title": clean_page_text(meta_title) or pdf_path.stem,
                "source_path": str(pdf_path),
                "source_name": pdf_path.name,
                "page_count": doc.page_count,
                "content_sha256_16": hashlib.sha256(file_bytes).hexdigest()[:16],
                "sha256_16": doc_id,
                "heading_source": heading_source,
            }
            if owner_id and owner_id != "local":
                meta["owner_id"] = owner_id
            rec = DocRecord(
                doc_id=doc_id,
                meta=meta,
                pages=pages,
                labels=labels,
                headings=headings,
                index=index,
                precision_index=precision_index,
            )
            self._docs[doc_id] = rec
            if source_name:
                rec.meta.update(source_name=source_name, title=Path(source_name).stem)
                rec.meta.pop("source_path", None)
            self._save_pdf_bytes(doc_id, file_bytes)
            self._persist(rec)
            logger.info(
                "ingest_ok doc_id=%s source_name=%s pages=%d headings=%d index_terms=%d",
                doc_id,
                pdf_path.name,
                meta["page_count"],
                len(headings),
                len(index),
            )
            return doc_id

    def delete_document(self, doc_id: str, *, owner_id: str | None = None) -> bool:
        """Remove one document from memory, disk, and Postgres (owner-scoped)."""
        if not (doc_id or "").strip():
            return False
        if owner_id and owner_id != "local" and not self.owned_by(doc_id, owner_id):
            # Still try DB with owner filter in case memory is cold.
            if self.use_db:
                try:
                    from app.db.repository import delete_document as db_delete

                    return bool(db_delete(doc_id, owner_id=owner_id))
                except Exception as exc:
                    logger.warning(
                        "store_db_delete_failed doc_id=%s error=%s",
                        doc_id,
                        type(exc).__name__,
                    )
            return False
        existed = doc_id in self._docs
        self._docs.pop(doc_id, None)
        path = self._path_for(doc_id)
        if path.exists():
            path.unlink(missing_ok=True)
            existed = True
        pdf_path = self._pdf_path_for(doc_id)
        if pdf_path.exists():
            pdf_path.unlink(missing_ok=True)
            existed = True
        if self.use_db:
            try:
                from app.db.repository import delete_document as db_delete

                if db_delete(doc_id, owner_id=owner_id):
                    existed = True
            except Exception as exc:
                logger.warning(
                    "store_db_delete_failed doc_id=%s error=%s",
                    doc_id,
                    type(exc).__name__,
                )
        if existed:
            logger.info("store_deleted doc_id=%s", doc_id)
        return existed

    def clear_all(self, *, owner_id: str | None = None) -> int:
        """Wipe documents (memory + JSON + DB). Owner-scoped when owner_id set."""
        if owner_id and owner_id != "local":
            owned = [
                did
                for did, rec in list(self._docs.items())
                if str(rec.meta.get("owner_id") or "") == str(owner_id)
            ]
            for did in owned:
                self._docs.pop(did, None)
                path = self._path_for(did)
                if path.exists():
                    path.unlink(missing_ok=True)
                pdf = self._pdf_path_for(did)
                if pdf.exists():
                    pdf.unlink(missing_ok=True)
            db_n = 0
            if self.use_db:
                try:
                    from app.db.repository import delete_all_documents

                    db_n = delete_all_documents(owner_id=owner_id)
                except Exception as exc:
                    logger.warning("store_db_clear_failed error=%s", type(exc).__name__)
            n = max(len(owned), db_n)
            logger.info("store_cleared count=%d owner_id=%s", n, owner_id)
            return n

        ids = list(self._docs.keys())
        for path in self.persist_dir.glob("*.json"):
            doc_id = path.stem
            if doc_id not in ids:
                ids.append(doc_id)
        self._docs.clear()
        for path in self.persist_dir.glob("*.json"):
            path.unlink(missing_ok=True)
        for path in self.persist_dir.glob("*.pdf"):
            path.unlink(missing_ok=True)
        db_n = 0
        if self.use_db:
            try:
                from app.db.repository import delete_all_documents

                db_n = delete_all_documents()
            except Exception as exc:
                logger.warning("store_db_clear_failed error=%s", type(exc).__name__)
        n = max(len(ids), db_n)
        logger.info("store_cleared count=%d", n)
        return n


_STORE: DocumentStore | None = None


def get_store() -> DocumentStore:
    """Return the process-wide DocumentStore singleton."""
    global _STORE
    if _STORE is None:
        _STORE = DocumentStore()
    return _STORE


def reset_store_for_tests(persist_dir: Path | None = None) -> DocumentStore:
    """Replace the singleton store (tests only). Never touch remote Postgres."""
    global _STORE
    _STORE = DocumentStore(persist_dir=persist_dir, use_db=False)
    return _STORE
