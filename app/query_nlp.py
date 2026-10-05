"""NLTK query processing; document evidence and literal indexing stay unchanged.

NLTK is imported on the first query plan, not at process startup, so PDF ingest
does not pay for the tokenizer.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.textutil import normalize_text

# Ship the small English corpus so no request or startup needs a download.
_DATA_DIR = str(Path(__file__).resolve().parent / "nltk_data")
_QUERY_STOPWORDS: frozenset[str] | None = None

# English stop lists include words that can change policy conditions. Keep them.
_MEANING_WORDS = frozenset({
    "no", "nor", "not", "n't", "before", "after", "until", "only",
    "above", "below", "under", "over", "between", "against", "without",
    "more", "less", "most", "few", "same",
})
_QUERY_FILLER = frozenset({
    "please", "tell", "document", "pdf", "prove", "define", "explain",
    "describe", "meaning", "compare", "ca", "wo",
})


def _ensure_nltk_path() -> None:
    import nltk.data

    if _DATA_DIR not in nltk.data.path:
        nltk.data.path.insert(0, _DATA_DIR)


def _load_query_stopwords() -> frozenset[str]:
    global _QUERY_STOPWORDS
    if _QUERY_STOPWORDS is None:
        from nltk.corpus import stopwords

        _ensure_nltk_path()
        _QUERY_STOPWORDS = (
            frozenset(stopwords.words("english")) | _QUERY_FILLER
        ) - _MEANING_WORDS
    return _QUERY_STOPWORDS


def __getattr__(name: str):
    if name == "QUERY_STOPWORDS":
        return _load_query_stopwords()
    raise AttributeError(name)

# NLTK normally separates symbol-bearing terms. Preserve their literal spelling,
# and preserve identifiers such as ISO-9001 or policy_id alongside normal words.
_TECHNICAL_RE = re.compile(
    r"\bo\s*\(\s*[^)\n]{1,24}\s*\)"
    r"|\b[A-Za-z][A-Za-z0-9]*\+\+"
    r"|\b[A-Za-z][A-Za-z0-9]*#"
    r"|\b[A-Za-z0-9]+\s*\*"
    r"|\b[A-Za-z0-9]+(?:[-_/][A-Za-z0-9]+)+\b",
    re.IGNORECASE,
)


def query_tokens(text: str) -> list[str]:
    """Ordered word tokens with intact technical terms; punctuation is excluded.

    preserve_line=True skips sentence segmentation, so punkt/punkt_tab data is
    unnecessary. This function intentionally does not remove stop words.
    """
    from nltk.tokenize import word_tokenize

    _ensure_nltk_path()
    normalized = normalize_text(text or "")
    tokens: list[str] = []
    cursor = 0
    for match in _TECHNICAL_RE.finditer(normalized):
        tokens.extend(word_tokenize(normalized[cursor:match.start()], preserve_line=True))
        tokens.append(re.sub(r"\s+", "", match.group(0)))
        cursor = match.end()
    tokens.extend(word_tokenize(normalized[cursor:], preserve_line=True))
    # preserve_line skips sentence splitting; a period on an earlier sentence
    # can remain attached to its word. Remove those edges before stop lookup.
    tokens = [token.strip(".,;:!?`\"") for token in tokens]
    return [token for token in tokens if any(ch.isalnum() for ch in token)]


def content_words(text: str) -> list[str]:
    """Keep ordered query words useful for keywords and heading matching."""
    stops = _load_query_stopwords()
    return [token for token in query_tokens(text) if token.lower() not in stops]
