"""One optional TOC pick when local heading overlap is weak.

The model may only choose existing heading titles or node ids from the
outline `list_headings` already returned. `use_terms` must be copied from
the question extract. New search terms are dropped.
"""

from __future__ import annotations

from typing import Any

from app.llm.client import get_llm
from app.prompts.system import sanitize_page_text

_TOC_SYSTEM = """Role: outline picker. Another step reads pages. You do not search and you do not answer.

Choose at most 3 sections from the outline. sections must be node ids (n0) or titles copied from the outline.
use_terms must be copied exactly from Allowed terms. Do not invent synonyms or new words.

JSON only:
{"sections":["n0"],"use_terms":["term from the allowed list"]}"""


def pick_toc(
    question: str,
    headings: list[dict[str, Any]],
    allowed_terms: list[str],
) -> dict[str, Any]:
    """Ask once for `{sections, use_terms}`. On failure, return an empty pick."""
    outline = _outline_lines(headings)
    if not outline:
        return {"sections": [], "use_terms": [], "headings": []}
    allowed = [str(term).strip() for term in allowed_terms if str(term).strip()]
    user = (
        f"Question:\n{question.strip()}\n\n"
        f"Allowed terms:\n" + "\n".join(f"- {term}" for term in allowed) + "\n\n"
        f"Outline:\n" + "\n".join(outline)
    )
    try:
        data = get_llm().complete_json(
            [
                {"role": "system", "content": _TOC_SYSTEM},
                {"role": "user", "content": user},
            ],
            temperature=0.0,
            light=True,
            max_attempts=1,
        )
    except Exception:
        return {"sections": [], "use_terms": [], "headings": []}
    if not isinstance(data, dict):
        return {"sections": [], "use_terms": [], "headings": []}
    return accept_toc_pick(data, headings, allowed)


def accept_toc_pick(
    raw: dict[str, Any] | None,
    headings: list[dict[str, Any]],
    allowed_terms: list[str],
) -> dict[str, Any]:
    """Keep node ids or exact titles, and use_terms that equal the extract."""
    raw = raw if isinstance(raw, dict) else {}
    allowed = {}
    for term in allowed_terms or []:
        text = str(term).strip()
        if text and text.lower() not in allowed:
            allowed[text.lower()] = text

    use_terms: list[str] = []
    for term in raw.get("use_terms") or []:
        key = str(term).strip().lower()
        if key in allowed and allowed[key] not in use_terms:
            use_terms.append(allowed[key])

    by_id: dict[str, dict[str, Any]] = {}
    by_title: dict[str, dict[str, Any]] = {}
    index_of: dict[int, int] = {}
    for i, heading in enumerate(headings or []):
        title = str(heading.get("title") or "").strip()
        if not title or title.startswith("("):
            continue
        by_id[f"n{i}"] = heading
        by_title.setdefault(title.lower(), heading)
        index_of[id(heading)] = i

    chosen: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw.get("sections") or []:
        key = str(item).strip()
        if not key:
            continue
        heading = by_id.get(key) or by_title.get(key.lower())
        if heading is None:
            continue
        title = str(heading.get("title") or "").strip().lower()
        if not title or title in seen:
            continue
        seen.add(title)
        chosen.append(heading)
        if len(chosen) >= 3:
            break

    return {
        "sections": [f"n{index_of[id(heading)]}" for heading in chosen],
        "use_terms": use_terms,
        "headings": chosen,
    }


def _outline_lines(headings: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for i, heading in enumerate(headings or []):
        title = str(heading.get("title") or "").strip()
        if not title or title.startswith("("):
            continue
        start = heading.get("start", heading.get("page", "?"))
        end = heading.get("end", start)
        lines.append(f"n{i}\t{sanitize_page_text(title)}\t{start}-{end}")
    return lines
