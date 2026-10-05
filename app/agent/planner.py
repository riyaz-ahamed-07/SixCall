from __future__ import annotations

import re
from typing import Any

from app.agent.intent import attach_intent
from app.llm.client import get_llm
from app.prompts.system import PLANNER_SYSTEM, build_planner_user
from app.query_nlp import content_words


def plan_question(question: str, headings: list[dict[str, Any]]) -> dict[str, Any]:
    # A direct topic question matching a heading needs no network planning.
    # Comparisons and less explicit requests retain the existing model planner.
    if re.match(r"^\s*(what\s+is|what\s+are|define|explain)\b", question, re.I):
        question_tokens = _content_tokens(question)
        for heading in headings:
            title = re.sub(r"^\d+(\.\d+)*\s*", "", str(heading.get("title") or "")).strip()
            if question_tokens and question_tokens == _content_tokens(title):
                data = _heuristic_plan(question, headings)
                data["keywords"] = [title]
                data["heading_hints"] = [title]
                return attach_intent(_normalize_plan(data, question, headings), question)
    messages = [
        {"role": "system", "content": PLANNER_SYSTEM},
        {"role": "user", "content": build_planner_user(question, headings)},
    ]

    try:
        data = get_llm().complete_json(
            messages, temperature=0.1, light=True, max_attempts=1
        )
    except Exception:
        data = _heuristic_plan(question, headings)

    plan = _normalize_plan(data, question, headings)
    return attach_intent(plan, question)


def _normalize_plan(
    data: dict[str, Any], question: str, headings: list[dict[str, Any]]
) -> dict[str, Any]:
    qtype = str(data.get("qtype") or "fact").lower()
    if qtype not in {"fact", "multi", "compare", "absent"}:
        qtype = "fact"

    keywords = [
        str(k).strip()
        for k in (data.get("keywords") or [])
        if str(k).strip() and _is_usable_keyword(str(k), question)
    ]
    if not keywords:
        keywords = _heuristic_keywords(question)

    heading_hints = [
        str(h).strip() for h in (data.get("heading_hints") or []) if str(h).strip()
    ]
    # Filter LLM heading hints that barely overlap the question (avoids path testing→planning)
    q_tokens = _content_tokens(question)
    related = set(q_tokens)
    if related & {"budget", "business", "plan", "cost", "revenue", "roi", "break"}:
        related |= {"cost", "revenue", "roi", "break", "budget", "business", "plan", "even"}
    filtered = []
    for hint in heading_hints:
        hint_clean = re.sub(r"^\d+(\.\d+)*\s*", "", hint).strip()
        if len(_content_tokens(hint_clean) & related) >= 2 or hint_clean.lower() in question.lower():
            filtered.append(hint_clean)
    heading_hints = filtered or _match_heading_hints(question, headings)

    return {
        "rewritten": str(data.get("rewritten") or question).strip(),
        "qtype": qtype,
        "keywords": keywords[:4],
        "heading_hints": heading_hints[:4],
        "contradiction_sensitive": bool(
            data.get("contradiction_sensitive")
            or _looks_contradiction_sensitive(question)
        ),
    }


def _heuristic_plan(question: str, headings: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "rewritten": question,
        "qtype": "absent" if _looks_absent(question) else "fact",
        "keywords": _heuristic_keywords(question),
        "heading_hints": _match_heading_hints(question, headings),
        "contradiction_sensitive": _looks_contradiction_sensitive(question),
    }


def _heuristic_keywords(question: str) -> list[str]:
    keywords: list[str] = []
    # Keep algorithm names like A* before generic tokenization strips them
    for m in re.finditer(r"\bA\s*[\*∗]\b|\bA\s*[\*∗]", question, re.I):
        keywords.append("A*")
        break

    phrases = re.findall(r'"([^"]+)"|“([^”]+)”', question)
    for a, b in phrases:
        p = (a or b).strip()
        if p:
            keywords.append(p)

    # NLTK words and cached stopwords; retain acronyms, numbers and symbols.
    for w in content_words(question):
        if w.lower() not in {k.lower() for k in keywords}:
            keywords.append(w)
        if len(keywords) >= 4:
            break

    # Expand common acronyms to a longer alternate for sparse indexes.
    expanded: list[str] = []
    for k in keywords:
        expanded.append(k)
        low = k.lower()
        if low == "ai" and "Artificial Intelligence" not in expanded:
            expanded.append("Artificial Intelligence")
        elif low == "ml" and "machine learning" not in {x.lower() for x in expanded}:
            expanded.append("machine learning")
    return expanded[:4] or [question.strip()[:40]]


def _is_usable_keyword(keyword: str, question: str) -> bool:
    """Reject planner keywords that are the whole question or stopword mush."""
    kw = (keyword or "").strip()
    if not kw:
        return False
    q = (question or "").strip()
    if kw.lower() == q.lower():
        return False
    return bool(content_words(kw))


def _match_heading_hints(question: str, headings: list[dict[str, Any]]) -> list[str]:
    q_tokens = _content_tokens(question)
    if not q_tokens:
        return []
    # Light synonym expand so "budget / business plan" finds Cost/Revenue headings.
    related = set(q_tokens)
    if related & {"budget", "business", "plan", "cost", "revenue", "roi", "break"}:
        related |= {"cost", "revenue", "roi", "break", "budget", "business", "plan", "even"}
    scored: list[tuple[int, str]] = []
    for h in headings:
        title = str(h.get("title") or "")
        # Drop leading section numbers like "2.2 "
        title_clean = re.sub(r"^\d+(\.\d+)*\s*", "", title).strip()
        h_tokens = _content_tokens(title_clean)
        if not h_tokens:
            continue
        overlap = len(related & h_tokens)
        # Require at least 2 overlapping content words, or exact phrase containment
        if overlap >= 2 or title_clean.lower() in question.lower():
            scored.append((overlap, title_clean))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [t for _, t in scored[:4]]


def _content_tokens(text: str) -> set[str]:
    return {token.lower() for token in content_words(text)}


def _looks_contradiction_sensitive(question: str) -> bool:
    q = question.lower()
    return any(
        k in q
        for k in (
            "amend",
            "supersede",
            "latest",
            "updated",
            "instead of",
            "replaced",
            "current",
            "contradict",
        )
    )


def _looks_absent(question: str) -> bool:
    q = question.lower()
    return any(k in q for k in ("is there any", "does it mention", "is it stated"))
