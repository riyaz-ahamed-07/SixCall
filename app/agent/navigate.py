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


def match_sections(question: str, headings: list[dict[str, Any]]) -> SectionMatch:
    """Token overlap between the question and heading titles."""
    q_tokens = {t.lower() for t in content_words(question)}
    scored: list[tuple[float, int, dict[str, Any]]] = []
    for heading in headings or []:
        title = str(heading.get("title") or "").strip()
        if not title or _SYNTHETIC_RE.match(title):
            continue
        t_tokens = _title_tokens(title)
        if not t_tokens or not q_tokens:
            continue
        overlap = q_tokens & t_tokens
        if not overlap:
            continue
        ratio = len(overlap) / len(t_tokens)
        scored.append((ratio, len(overlap), heading))

    scored.sort(key=lambda item: (-item[0], -item[1], str(item[2].get("title") or "")))
    # A title is a real hit when half its content words are in the question,
    # or at least two content words overlap.
    kept = [h for ratio, count, h in scored if ratio >= 0.5 or count >= 2]
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
    """Pages to read before the first answer.

    Default window is min(budget, 3). Multi / compare / supersede may use 4.
    When more candidates remain, hold one call for a repair get_page.
    """
    if budget_left <= 0 or not ranked:
        return []
    limit = 4 if wide else 3
    slots = min(budget_left, limit, len(ranked))
    if len(ranked) > slots and budget_left - slots > 1:
        slots = min(len(ranked), budget_left - 1, 4)
    if (
        budget_left >= 2
        and len(ranked) > slots
        and budget_left - slots == 0
        and slots > 1
    ):
        slots -= 1
    return ranked[:slots]
