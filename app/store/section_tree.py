"""Section tree built at ingest from page text when the PDF has no usable outline.

Preference order lives in the store: TOC, then font size, then these lexical cues.
"""

from __future__ import annotations

import re

_NUM_HEAD_RE = re.compile(
    r"^(?P<num>\d+(?:\.\d+){0,4})\s+(?P<title>[A-Z][^\n]{2,90})$"
)
_WORD_HEAD_RE = re.compile(
    r"^(?P<kind>chapter|section|article|part|annex|schedule)\s+"
    r"(?P<num>\d+|[IVXLC]+)\b[.):]?\s+(?P<title>\S.{2,90})$",
    re.I,
)
_CAPS_RE = re.compile(r"^[A-Z][A-Z0-9][A-Z0-9 /,&-]{3,70}$")


def lexical_heading_candidates(pages: dict[int, str]) -> list[tuple[int, str, int]]:
    """Return (level, title, page) from numbering and heading-shaped lines."""
    found: list[tuple[int, str, int]] = []
    seen: set[tuple[int, str]] = set()
    for page_no in sorted(pages):
        for raw_line in (pages.get(page_no) or "").splitlines():
            line = " ".join(raw_line.strip().split())
            if not line or len(line) > 100 or line.endswith("."):
                continue
            level: int | None = None
            title = ""
            numbered = _NUM_HEAD_RE.match(line)
            named = _WORD_HEAD_RE.match(line)
            if numbered:
                title = f"{numbered.group('num')} {numbered.group('title').strip()}"
                level = numbered.group("num").count(".") + 1
            elif named:
                kind = named.group("kind").capitalize()
                title = f"{kind} {named.group('num')} {named.group('title').strip()}"
                level = 1
            elif _CAPS_RE.match(line) and 1 < len(line.split()) <= 8:
                title = line.title()
                level = 1
            if level is None or not title:
                continue
            key = (page_no, title.lower())
            if key in seen:
                continue
            seen.add(key)
            found.append((level, title, page_no))
    return found
