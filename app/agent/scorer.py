from __future__ import annotations

import math
from collections import Counter
from typing import Any


def score_pages(
    *,
    keyword_hits: dict[str, list[int]],
    headings: list[dict[str, Any]],
    heading_hints: list[str],
    contradiction_sensitive: bool,
    top_k: int = 3,
) -> list[int]:
    """
    Tree + keyword combine (not vector search, not MCTS).

    Prefer pages in BOTH keyword hits and heading ranges, then rare hits, then neighbors.
    """
    hit_sets: dict[str, set[int]] = {}
    all_hits: set[int] = set()
    nonempty_sets: list[set[int]] = []
    df: Counter[str] = Counter()

    for kw, pages in keyword_hits.items():
        uniq = {int(p) for p in pages}
        if not uniq:
            continue
        hit_sets[kw] = uniq
        df[kw] = len(uniq)
        all_hits.update(uniq)
        nonempty_sets.append(uniq)

    if not all_hits:
        return []

    inter = set.intersection(*nonempty_sets) if len(nonempty_sets) >= 2 else set()
    n_docs = max(1, len(all_hits))
    idf = {
        kw: math.log(1.0 + (n_docs / max(1, df[kw]))) for kw in hit_sets
    }

    tree_pages = _pages_in_heading_hints(headings, heading_hints, keyword_hits)

    rarest_pages: set[int] = set()
    if hit_sets:
        rarest_kw = min(hit_sets, key=lambda k: len(hit_sets[k]))
        rarest_pages = set(hit_sets[rarest_kw])

    # Always include heading-matched section pages. Keyword hits alone often land
    # on TOC pages; the outline start/end is the real content.
    candidates = set(all_hits) | set(tree_pages)
    if not candidates:
        return []

    # "both" = true keyword hit ∩ tree (do not award to expanded-only neighbors).
    both = tree_pages & all_hits
    both_rare = tree_pages & rarest_pages
    # TOC-only miss: keyword hit early pages, section lives later in the outline.
    outline_rescue = bool(tree_pages) and not both

    scores: dict[int, float] = {}
    max_page = max(candidates)

    for page in candidates:
        score = 0.0
        hits_here = 0
        for kw, pageset in hit_sets.items():
            if page in pageset:
                score += idf.get(kw, 1.0)
                hits_here += 1
        if hits_here > 1:
            score += 1.0 * (hits_here - 1)
        if page in inter:
            score += 1.5
        if page in rarest_pages:
            score += 2.0
        if page in all_hits and page in tree_pages:
            score += 3.0
        if page in both:
            score += 5.0
        if page in both_rare:
            score += 2.5
        # Prefer outline section pages over TOC-only keyword hits.
        if page in tree_pages:
            score += 4.0 if outline_rescue else 1.0
        later = page / max_page
        if contradiction_sensitive:
            score += 0.45 * later
        else:
            score += 0.05 * later
        scores[page] = score

    ranked = sorted(
        scores.keys(),
        key=lambda p: (
            scores[p],
            -p if not contradiction_sensitive else p,
        ),
        reverse=True,
    )

    chosen: list[int] = []
    for pool in (
        sorted(both_rare, key=lambda p: -scores.get(p, 0)),
        sorted(both - both_rare, key=lambda p: -scores.get(p, 0)),
        ranked,
    ):
        for p in pool:
            if p not in chosen and p in scores:
                chosen.append(p)
            if len(chosen) >= top_k:
                break
        if len(chosen) >= top_k:
            break

    if contradiction_sensitive and ranked:
        latest = max(ranked)
        if latest not in chosen:
            if len(chosen) >= top_k:
                chosen[-1] = latest
            else:
                chosen.append(latest)

    return chosen[:top_k]


def _pages_in_heading_hints(
    headings: list[dict[str, Any]],
    heading_hints: list[str],
    keyword_hits: dict[str, list[int]] | None = None,
) -> set[int]:
    pages: set[int] = set()
    hints = [h.lower() for h in heading_hints if h]
    kw_bits: list[str] = []
    if keyword_hits:
        seen: set[str] = set()
        for kw in keyword_hits:
            for bit in (kw.lower().replace("*", "star"), kw.lower()):
                if bit and bit not in seen:
                    seen.add(bit)
                    kw_bits.append(bit)

    for h in headings:
        title = str(h.get("title") or "")
        title_l = title.lower().strip()
        title_norm = title_l.replace("∗", "*").replace("*", "star")
        if title_l.startswith(("fig.", "figure", "table", "eq.")):
            continue
        matched = False
        if hints:
            for hint in hints:
                if hint == title_l or title_l == hint or title_l.startswith(hint):
                    matched = True
                    break
                if hint in title_l and len(title_l) <= len(hint) + 24:
                    matched = True
                    break
        if not matched and kw_bits:
            hits = sum(1 for b in kw_bits if b and (b in title_l or b in title_norm))
            if any(
                b == title_l
                or b == title_norm
                or title_l.startswith(b)
                or b.startswith(title_l)
                for b in kw_bits
                if len(b) >= 8
            ):
                matched = True
            elif hits >= 1 and any(
                token in title_l or token in title_norm
                for token in ("optim", "optimal", "proof", "theorem")
            ):
                matched = True
            elif hits >= 2:
                matched = True
        if matched:
            start = int(h.get("start") or 1)
            end = int(h.get("end") or start)
            for p in range(start, end + 1):
                pages.add(p)
    return pages
