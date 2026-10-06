"""Local section walk: heading-title overlap, then which pages to read.

No model calls. Page choice is a budgeted prefix of this ranking.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.query_nlp import content_words

_NUM_PREFIX_RE = re.compile(r"^\d+(?:\.\d+)*\s+")
_SYNTHETIC_RE = re.compile(r"^\(.*\)$")


@dataclass
class SectionMatch:
    strong: bool
    headings: list[dict[str, Any]] = field(default_factory=list)
    ranges: list[tuple[int, int]] = field(default_factory=list)
    starts: list[int] = field(default_factory=list)

    @property
    def titles(self) -> list[str]:
        return [str(h.get("title") or "") for h in self.headings]


def _title_tokens(title: str) -> set[str]:
    cleaned = _NUM_PREFIX_RE.sub("", title or "")
    return {t.lower() for t in content_words(cleaned)}


def _phrase_in_title(phrase: str, title: str, title_tokens: set[str]) -> bool:
    phrase = (phrase or "").strip().lower()
    if not phrase:
        return False
    if " " in phrase:
        return phrase in (title or "").lower()
    return phrase in title_tokens


def match_sections(
    question: str,
    headings: list[dict[str, Any]],
    entities: list[str] | None = None,
) -> SectionMatch:
    """Score heading titles by token and phrase overlap. No embeddings.

    A title matches when half its content words are in the question, at least
    two content words overlap, or an extracted question phrase sits in the
    title. At most three ranges are kept.
    """
    q_tokens = {t.lower() for t in content_words(question)}
    phrases = [str(item).strip() for item in (entities or []) if str(item).strip()]
    scored: list[tuple[float, int, int, dict[str, Any]]] = []
    for heading in headings or []:
        title = str(heading.get("title") or "").strip()
        if not title or _SYNTHETIC_RE.match(title):
            continue
        t_tokens = _title_tokens(title)
        if not t_tokens and not phrases:
            continue
        overlap = q_tokens & t_tokens
        phrase_hits = sum(1 for phrase in phrases if _phrase_in_title(phrase, title, t_tokens))
        if not overlap and not phrase_hits:
            continue
        ratio = (len(overlap) / len(t_tokens)) if t_tokens else 0.0
        if ratio < 0.5 and len(overlap) < 2 and phrase_hits == 0:
            continue
        scored.append((ratio, len(overlap), phrase_hits, heading))

    scored.sort(
        key=lambda item: (
            -item[0],
            -item[1],
            -item[2],
            str(item[3].get("title") or ""),
        )
    )
    kept = [heading for _ratio, _count, _phrases, heading in scored[:3]]
    strong = bool(kept)
    ranges: list[tuple[int, int]] = []
    starts: list[int] = []
    for heading in kept:
        start = int(heading.get("start") or 1)
        end = int(heading.get("end") or start)
        if end < start:
            end = start
        ranges.append((start, end))
        if start not in starts:
            starts.append(start)
    return SectionMatch(strong=strong, headings=kept, ranges=ranges, starts=starts)


def _in_ranges(page: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= page <= end for start, end in ranges)


def choose_pages(
    *,
    keyword_hits: dict[str, list[int]],
    sections: SectionMatch,
    supersede: bool,
    ensure_each_hit: bool,
    top_k: int,
) -> list[int]:
    """Order pages to read. Supersede lock keeps max(keyword hit) in the list."""
    all_hits: list[int] = []
    for pages in keyword_hits.values():
        for page in pages:
            if page not in all_hits:
                all_hits.append(int(page))
    latest = max(all_hits) if all_hits and supersede else None

    in_section = [p for p in all_hits if sections.ranges and _in_ranges(p, sections.ranges)]
    outside = [p for p in all_hits if not sections.ranges or not _in_ranges(p, sections.ranges)]
    if sections.ranges:
        # Section filter drops hits outside the matched range, then the lock
        # puts the latest keyword page back when a later statement can win.
        pool = list(dict.fromkeys([*in_section, *sections.starts]))
        if latest is not None and latest not in pool:
            pool.append(latest)
    else:
        pool = list(dict.fromkeys([*sections.starts, *all_hits]))

    ranked: list[int] = []
    if latest is not None:
        ranked.append(latest)

    def push(pages: list[int]) -> None:
        for page in pages:
            if page not in ranked:
                ranked.append(page)

    push(in_section)
    push(sections.starts)
    push(pool)
    # Hits outside the section stay behind the section pages. The supersede
    # lock already placed max(keyword hit) at the front when it applies.
    push(outside)

    if ensure_each_hit:
        ranked = _cover(ranked, keyword_hits, max(top_k, 1), locked=latest)

    if latest is not None and latest not in ranked[: max(top_k, 1)]:
        head = [latest, *[p for p in ranked if p != latest]]
        ranked = head

    return ranked


def apply_supersede_lock(fetch: list[int], latest: int | None) -> list[int]:
    """Force the newest keyword hit into the pages that will be read.

    Later statement supersedes earlier. A section filter must not drop that
    page. When the window is full, drop the lowest-priority non-latest page
    so evidence reads stay within the budget.
    """
    pages = [int(p) for p in fetch]
    if latest is None:
        return pages
    latest = int(latest)
    if latest in pages:
        return pages
    if not pages:
        return [latest]
    # Later statement supersedes earlier.
    return [*pages[:-1], latest]


def optional_search_keeps_reads(budget_left: int) -> bool:
    """True when one more search still leaves at least two evidence reads."""
    return budget_left >= 3


def _cover(
    ranked: list[int],
    keyword_hits: dict[str, list[int]],
    window: int,
    *,
    locked: int | None,
) -> list[int]:
    front = list(ranked[:window])
    rest = [p for p in ranked if p not in front]
    for pages in keyword_hits.values():
        if not pages or any(p in front for p in pages):
            continue
        pick = int(pages[0])
        if pick in front:
            continue
        if len(front) < window:
            front.append(pick)
            rest = [p for p in rest if p != pick]
            continue
        victim = next((i for i in range(len(front) - 1, -1, -1) if front[i] != locked), None)
        if victim is None:
            continue
        displaced = front.pop(victim)
        front.append(pick)
        rest = [p for p in rest if p != pick]
        if displaced not in front and displaced not in rest:
            rest.append(displaced)
    return list(dict.fromkeys([*front, *rest]))


def select_initial_pages(ranked: list[int], budget_left: int, *, wide: bool) -> list[int]:
    """Read the affordable selected pages before the only final generation."""
    limit = 4 if wide else 3
    return list(dict.fromkeys(ranked))[:max(0, min(budget_left, limit))]
