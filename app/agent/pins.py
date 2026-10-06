"""Question-only search pins.

Every pin is a substring of the user question. Nothing is expanded to a
synonym or a longer name the question did not contain.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

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
_CLAUSE_RE = re.compile(
    r"\b(?:clause|section|article|paragraph)\s+\d+(?:\.\d+)*\b"
    r"|\b\d+\.\d+(?:\.\d+)*\b",
    re.I,
)
_NUM_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
_MONTH = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)
_DATE_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}\b"
    r"|\b\d{1,2}/\d{1,2}/\d{2,4}\b"
    rf"|\b(?:{_MONTH})\s+\d{{1,2}}(?:,\s*\d{{4}})?\b"
    rf"|\b\d{{1,2}}\s+(?:{_MONTH})(?:\s+\d{{4}})?\b",
    re.I,
)
_NEGATION_CUE_RE = re.compile(r"\b(?:not|no|except)\b", re.I)
_CAP_RE = re.compile(r"\b[A-Z][A-Za-z0-9]*\b")
_START_Q_RE = re.compile(
    r"^\s*(what|where|when|why|who|how|which|is|are|do|does|can|could|should|would)\b",
    re.I,
)
# A later statement can supersede an earlier one. Recorded from the question only.
_SUPERSEDE_RE = re.compile(
    r"\b(amend\w*|supersed\w*|latest|revised|replaced|current|update\w*)\b",
    re.I,
)
# Modifiers that describe time, not the thing to look up.
_WEAK = frozenset({
    "latest", "after", "before", "current", "update", "updates", "updated",
    "earlier", "previous", "instead", "amended", "today", "now",
})
_TERM_CAP = 8


@dataclass
class QuestionExtract:
    """Entities copied from the question. `terms` is the search-pin list."""

    terms: list[str] = field(default_factory=list)
    numbers: list[str] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    capwords: list[str] = field(default_factory=list)
    quotes: list[str] = field(default_factory=list)
    clause_ids: list[str] = field(default_factory=list)
    negations: list[str] = field(default_factory=list)
    supersede_cues: list[str] = field(default_factory=list)
    supersede: bool = False

    def allowed_keys(self) -> set[str]:
        """Normalized forms a search_keyword term is allowed to use."""
        pool = [
            *self.terms,
            *self.numbers,
            *self.dates,
            *self.capwords,
            *self.quotes,
            *self.clause_ids,
        ]
        return {_norm_term(item) for item in pool if _norm_term(item)}


def _norm_term(term: str) -> str:
    return re.sub(r"\s+", " ", normalize_text(term or "").lower()).strip()


def term_in_question(term: str, question: str) -> bool:
    """True when `term` is contained in the question after light normalization."""
    q = _norm_term(question)
    t = _norm_term(term)
    return bool(t) and t in q


def term_allowed(term: str, extract: QuestionExtract) -> bool:
    """True when `term` is the extract entry or a trivial case/space normalization of it."""
    key = _norm_term(term)
    return bool(key) and key in extract.allowed_keys()


def extract_question(question: str) -> QuestionExtract:
    """Numbers, CapWords, quotes, clause ids, and content phrases from the question."""
    question = question or ""
    cues = [match.group(0) for match in _SUPERSEDE_RE.finditer(question)]
    extract = QuestionExtract(supersede=bool(cues), supersede_cues=cues)
    pins: list[str] = []

    def add(term: str) -> None:
        term = re.sub(r"\s+", " ", (term or "").strip())
        if not term or not term_in_question(term, question):
            return
        if term.lower() in {p.lower() for p in pins}:
            return
        pins.append(term)

    def remember(bucket: list[str], term: str) -> None:
        term = re.sub(r"\s+", " ", (term or "").strip())
        if not term or term.lower() in {item.lower() for item in bucket}:
            return
        if not term_in_question(term, question):
            return
        bucket.append(term)

    for match in _QUOTE_RE.finditer(question):
        quoted = match.group(1) or match.group(2) or ""
        remember(extract.quotes, quoted)
        add(quoted)

    for match in _CLAUSE_RE.finditer(question):
        remember(extract.clause_ids, match.group(0))
        add(match.group(0))

    for match in _DATE_RE.finditer(question):
        remember(extract.dates, match.group(0))
        add(match.group(0))

    for match in _NEGATION_CUE_RE.finditer(question):
        remember(extract.negations, match.group(0).lower())

    for match in _NUM_RE.finditer(question):
        remember(extract.numbers, match.group(0))
        add(match.group(0))

    lead = _START_Q_RE.match(question)
    lead_at = lead.start(1) if lead else None
    for match in _CAP_RE.finditer(question):
        word = match.group(0)
        if lead_at is not None and match.start() == lead_at:
            continue
        if len(word) < 2 or word.lower() in QUERY_STOPWORDS or word.lower() in _WEAK:
            continue
        remember(extract.capwords, word)
        add(word)

    for match in _TECH_RE.finditer(question):
        raw = match.group(0)
        add(re.sub(r"\s+", "", raw) if "*" in raw else raw)

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
        if tok.lower() in _WEAK or tok.lower() in {"not", "no", "except"}:
            continue
        add(tok)

    pins.sort(key=lambda p: (-len(p.split()), -len(p), p.lower()))
    extract.terms = pins[:_TERM_CAP]
    return extract


def extract_pins(question: str, *, limit: int = 4) -> list[str]:
    """Distinctive phrases and words copied from the question, longest first."""
    return extract_question(question).terms[:limit]


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
