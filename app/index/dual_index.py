"""Dual lexical index for search_keyword.

Precision keeps unstemmed numbers, CapWords, clause-like phrases, and exact
phrases taken from page text. Recall is the stemmed bag built beside it.
Lookup tries precision first and falls back to recall. Results are page
numbers; this module never returns snippets.
"""

from __future__ import annotations

import re
from collections import defaultdict

from app.textutil import normalize_text

# Small closed list so phrase picking does not depend on the agent package.
_STOP = frozenset({
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "with",
    "by", "from", "at", "as", "is", "are", "was", "were", "be", "been",
    "this", "that", "these", "those", "it", "its", "we", "you", "they",
    "our", "your", "their", "not", "no", "but", "if", "than", "then",
    "into", "over", "under", "about", "after", "before", "between",
})

_TOKEN_RE = re.compile(
    r"[A-Za-z][A-Za-z0-9]*\+\+|[A-Za-z]#|[A-Za-z0-9]+\*|\d+(?:\.\d+)?|[A-Za-z][A-Za-z0-9'-]*"
)
_CLAUSE_RE = re.compile(
    r"\b(?:clause|section|article|paragraph|annex|schedule|part)\s+\d+(?:\.\d+)*\b",
    re.I,
)
_NUM_UNIT_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s+(?:days?|months?|years?|hours?|percent|dollars?|pages?|usd)\b",
    re.I,
)
_MAX_PHRASES_PER_PAGE = 400


def _key(text: str) -> str:
    return re.sub(r"\s+", " ", normalize_text(text).lower()).strip()


def _add(index: dict[str, set[int]], phrase: str, page_no: int) -> None:
    key = _key(phrase)
    if len(key) < 1:
        return
    index[key].add(page_no)


def build_precision_index(pages: dict[int, str]) -> dict[str, list[int]]:
    """Unstemmed precision postings: number / CapWord / phrase → sorted pages."""
    index: dict[str, set[int]] = defaultdict(set)
    for page_no, text in pages.items():
        raw = normalize_text(text or "")
        if not raw:
            continue
        added = 0
        for match in _TOKEN_RE.finditer(raw):
            tok = match.group(0)
            if any(ch.isdigit() for ch in tok) or any(ch in tok for ch in "*+#"):
                _add(index, tok, page_no)
                continue
            # CapWords and acronyms only — plain lowercase words stay on recall.
            if tok[:1].isupper() or (len(tok) >= 2 and tok.isupper()):
                _add(index, tok, page_no)
        for cre in (_CLAUSE_RE, _NUM_UNIT_RE):
            for match in cre.finditer(raw):
                _add(index, match.group(0), page_no)
                added += 1
        tokens = list(_TOKEN_RE.finditer(raw))
        for i, match in enumerate(tokens):
            if added >= _MAX_PHRASES_PER_PAGE:
                break
            word = match.group(0)
            if _key(word) in _STOP:
                continue
            for width in (2, 3):
                if i + width > len(tokens):
                    continue
                group = tokens[i : i + width]
                # Adjacent in the token stream (finditer already skips punctuation).
                if group[-1].start() - group[0].end() > 40:
                    continue
                words = [g.group(0) for g in group]
                if any(_key(w) in _STOP for w in words):
                    continue
                if not any(
                    w[:1].isupper() or any(ch.isdigit() for ch in w) or any(ch in w for ch in "*+#")
                    for w in words
                ) and width == 3:
                    # Trigrams need a distinctive token; bigrams of content words are kept.
                    continue
                _add(index, " ".join(words), page_no)
                added += 1
    return {k: sorted(v) for k, v in index.items()}


def precision_lookup(index: dict[str, list[int]], keyword: str) -> list[int] | None:
    """Return precision pages, or None so the caller can fall back to recall.

    A lowercase single word is not answered from the CapWord postings. Those
    postings only record capitalized forms, so using them alone would hide
    later lowercase mentions of the same word.
    """
    raw = normalize_text(keyword or "").strip()
    if not raw or not index:
        return None
    low = _key(raw)
    pages = index.get(low)
    if not pages:
        return None
    distinctive = (
        " " in low
        or any(ch.isdigit() for ch in low)
        or any(ch in low for ch in "*+#")
        or any(ch.isupper() for ch in raw)
    )
    if not distinctive:
        return None
    return list(pages)
