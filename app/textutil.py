from __future__ import annotations

import re
import unicodedata

# PDF / Unicode forms that break naive exact keyword lookup
_CHAR_MAP = str.maketrans(
    {
        # asterisks / stars
        "\u2217": "*",  # ∗
        "\u066D": "*",
        "\u204E": "*",
        "\uFF0A": "*",
        "\uFE61": "*",
        "\u2605": "*",
        # dashes / minus
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",  # –
        "\u2014": "-",  # —
        "\u2212": "-",  # −
        "\uFE58": "-",
        "\uFE63": "-",
        "\uFF0D": "-",
        # quotes / apostrophes
        "\u2018": "'",
        "\u2019": "'",
        "\u201A": "'",
        "\u201B": "'",
        "\u201C": '"',
        "\u201D": '"',
        "\u00B4": "'",
        "\u0060": "'",
        # spaces
        "\u00A0": " ",  # nbsp
        "\u202F": " ",
        "\u2007": " ",
        "\u2009": " ",
        "\u200A": " ",
        "\u200B": "",  # zero-width space
        "\u200C": "",
        "\u200D": "",
        "\uFEFF": "",
        "\u00AD": "",  # soft hyphen
        # misc
        "\u2026": "...",
        "\u00B7": "*",  # · sometimes used for A·search after bad encode
    }
)

# Common Latin ligatures → decomposed letters (fi/fl/…)
_LIGATURES = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\ufb05": "ft",
    "\ufb06": "st",
    "\u00e6": "ae",
    "\u0153": "oe",
}

_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'_-]{1,}")
_STAR_TOKEN_RE = re.compile(r"[A-Za-z0-9]+\*")
_PLUSPLUS_RE = re.compile(r"[A-Za-z]#?\+\+")  # C++, G++
_SHARP_RE = re.compile(r"[A-Za-z]#")  # C#
_BIGO_RE = re.compile(r"\bo\s*\(\s*[^)]{1,24}\s*\)", re.I)
_CID_RE = re.compile(r"\(cid:\d+\)", re.I)
_WS_RE = re.compile(r"[ \t]+")


def normalize_asterisks(text: str) -> str:
    """Backward-compatible helper used by older call sites."""
    return normalize_text(text)


def normalize_text(text: str) -> str:
    """Canonical form for indexing, search queries, and quote checks."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    for src, dst in _LIGATURES.items():
        if src in text:
            text = text.replace(src, dst)
    text = text.translate(_CHAR_MAP)
    return text


def collapse_ws(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [_WS_RE.sub(" ", ln).strip() for ln in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def tokenize(text: str) -> list[str]:
    text = normalize_text(text).lower()
    found: list[str] = []
    found.extend(_PLUSPLUS_RE.findall(text))
    found.extend(_SHARP_RE.findall(text))
    found.extend(_STAR_TOKEN_RE.findall(text))
    found.extend(
        re.sub(r"\s+", "", m.group(0)).lower() for m in _BIGO_RE.finditer(text)
    )
    found.extend(_WORD_RE.findall(text))

    seen: set[str] = set()
    out: list[str] = []
    for tok in found:
        tok = tok.lower()
        if tok and tok not in seen:
            seen.add(tok)
            out.append(tok)
    return out


def keyword_aliases(keyword: str) -> list[str]:
    """
    Expand a user/planner keyword into equivalent lookup forms.
    Done inside search_keyword so aliases do not burn extra tool-call budget.
    """
    raw = (keyword or "").strip()
    if not raw:
        return []
    base = normalize_text(raw)
    aliases: list[str] = [raw, base]

    compact = re.sub(r"\s+", "", base.lower())
    # A* family (also A· after bad PDF encode, A-star, astar)
    if re.fullmatch(r"a[\*·.]?", compact) or compact in {
        "a*",
        "astar",
        "a-star",
        "a∗",
        "a*search",
        "astarsearch",
    }:
        aliases.extend(
            [
                "A*",
                "A∗",
                "A-star",
                "A star",
                "astar",
                "A*search",
                "A∗search",
            ]
        )

    if compact in {"c++", "cplusplus", "cplus"}:
        aliases.extend(["C++", "c++", "cplusplus"])

    if compact in {"c#", "csharp"}:
        aliases.extend(["C#", "c#", "csharp"])

    if compact in {"ai"}:
        aliases.extend(["AI", "Artificial Intelligence", "artificial intelligence"])

    if compact in {"ml"}:
        aliases.extend(["ML", "machine learning", "Machine Learning"])

    if re.fullmatch(r"o\([a-z0-9+\-]+\)", compact):
        aliases.append(compact)
        aliases.append(compact.upper())

    # Strip trailing punctuation variants
    stripped = base.strip(".,;:!?()[]{}\"'")
    if stripped and stripped != base:
        aliases.append(stripped)

    # Dedupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for a in aliases:
        a = a.strip()
        key = normalize_text(a).lower()
        if a and key not in seen:
            seen.add(key)
            out.append(a)
    return out


def garbage_ratio(text: str) -> float:
    """Fraction of unusable extraction glyphs (FFFD / cid:N)."""
    if not text:
        return 1.0
    n = len(text)
    bad = text.count("\ufffd") + sum(len(m) for m in _CID_RE.findall(text))
    return bad / max(1, n)


def needs_ocr(text: str, *, min_chars: int = 20, garbage_thresh: float = 0.15) -> bool:
    cleaned = (text or "").strip()
    if len(cleaned) < min_chars:
        return True
    return garbage_ratio(cleaned) >= garbage_thresh
