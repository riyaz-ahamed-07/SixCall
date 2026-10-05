"""Question-only search pins.

Every pin is a substring of the user question. Nothing is expanded to a
synonym or a longer name the question did not contain.
"""

from __future__ import annotations

import re

from app.query_nlp import QUERY_STOPWORDS, content_words, query_tokens
from app.textutil import normalize_text

_TECH_RE = re.compile(
    r"\b[A-Za-z][A-Za-z0-9]*\+\+"
    r"|\b[A-Za-z]#"
    r"|\b[A-Za-z0-9]+\s*\*"
    r"|\b[A-Za-z0-9]+(?:[-_/][A-Za-z0-9]+)+\b"
    r"|\b\d+(?:\.\d+)?(?:\s+[A-Za-z]{3,12})?",
    re.I,
)
_QUOTE_RE = re.compile(r'"([^"]+)"|“([^”]+)”')
# Modifiers that describe time, not the thing to look up.
_WEAK = frozenset({
    "latest", "after", "before", "current", "updated", "earlier", "previous",
    "instead", "amended", "today", "now",
})


def term_in_question(term: str, question: str) -> bool:
    """True when `term` is contained in the question after light normalization."""
    q = re.sub(r"\s+", " ", normalize_text(question or "").lower())
    t = re.sub(r"\s+", " ", normalize_text(term or "").lower())
    return bool(t) and t in q


def extract_pins(question: str, *, limit: int = 4) -> list[str]:
    """Distinctive phrases and words copied from the question, longest first."""
    question = question or ""
    pins: list[str] = []

    def add(term: str) -> None:
        term = re.sub(r"\s+", " ", (term or "").strip())
        if not term or not term_in_question(term, question):
            return
        if term.lower() in {p.lower() for p in pins}:
            return
        pins.append(term)

    for match in _QUOTE_RE.finditer(question):
        add(match.group(1) or match.group(2) or "")

    for match in _TECH_RE.finditer(question):
        add(re.sub(r"\s+", "", match.group(0)) if "*" in match.group(0) else match.group(0))

    tokens = query_tokens(question)
    for i in range(len(tokens) - 1):
        a, b = tokens[i], tokens[i + 1]
        if a.lower() in QUERY_STOPWORDS or b.lower() in QUERY_STOPWORDS:
            continue
        if a.lower() in _WEAK or b.lower() in _WEAK:
            continue
        if len(a) < 3 or len(b) < 3:
            continue
        add(f"{a} {b}")

    for tok in content_words(question):
        if not _keep_unigram(tok):
            continue
        if tok.lower() in _WEAK:
            continue
        add(tok)

    pins.sort(key=lambda p: (-len(p.split()), -len(p), p.lower()))
    return pins[:limit]


def _keep_unigram(tok: str) -> bool:
    if any(ch in tok for ch in "*+#"):
        return True
    if any(ch.isdigit() for ch in tok):
        return True
    if len(tok) >= 4:
        return True
    if len(tok) >= 2 and tok.isupper():
        return True
    return False
