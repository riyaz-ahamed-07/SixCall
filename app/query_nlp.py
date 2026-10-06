"""NLTK query processing; document evidence and literal indexing stay unchanged."""

from __future__ import annotations

import re
from pathlib import Path

import nltk.data
from nltk.corpus import stopwords
from nltk.tokenize import word_tokenize

from app.textutil import normalize_text

# Ship the small English corpus so no request or startup needs a download.
_DATA_DIR = str(Path(__file__).resolve().parent / "nltk_data")
if _DATA_DIR not in nltk.data.path:
    nltk.data.path.insert(0, _DATA_DIR)

# English stop lists include words that can change policy conditions. Keep them.
_MEANING_WORDS = frozenset({
    "no", "nor", "not", "n't", "except", "before", "after", "until", "only",
    "above", "below", "under", "over", "between", "against", "without",
    "more", "less", "most", "few", "same",
})
_QUERY_FILLER = frozenset({
    "please", "tell", "document", "pdf", "prove", "define", "explain",
    "describe", "meaning", "compare", "ca", "wo",
})
QUERY_STOPWORDS = (
    frozenset(stopwords.words("english")) | _QUERY_FILLER
) - _MEANING_WORDS

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
    """Keep ordered query words useful for keywords and heading matching.

    Digits, and the cues not/no/except, are never treated as filler.
    """
    kept: list[str] = []
    for token in query_tokens(text):
        if any(ch.isdigit() for ch in token):
            kept.append(token)
            continue
        if token.lower() not in QUERY_STOPWORDS:
            kept.append(token)
    return kept
