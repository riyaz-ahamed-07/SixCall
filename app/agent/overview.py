from __future__ import annotations

import re
import uuid
from typing import Any

from app.agent.abstain import format_abstain_text
from app.agent.answerer import draft_answer
from app.agent.verifier import verify_quotes
from app.config import REQUEST_DEADLINE_SEC
from app.deadline import DeadlineExceededError, clear_deadline, start_deadline
from app.tools.get_page import get_page
from app.tools.list_headings import list_headings
from app.tools.wrapper import (
    BudgetExceededError,
    clear_active_session,
    start_question,
)

# 1 headings + up to 5 pages = 6 calls max
_MAX_OVERVIEW_PAGES = 5

# Whole-document overview only — not topic summaries ("summarize the refund policy").
_OVERVIEW_RE = re.compile(
    r"^\s*("
    r"what\s+is\s+this\s+document\s+about|"
    r"what'?s\s+this\s+(doc|document|pdf)\s+about|"
    r"what\s+does\s+this\s+(document|pdf|paper)\s+(cover|discuss|say)|"
    r"give\s+(me\s+)?(a\s+)?(brief\s+|short\s+)?summary|"
    r"summarize(\s+(this|the)(\s+(document|pdf|paper))?)?|"
    r"overview\s+of\s+(this|the)\s+(document|pdf|paper)|"
    r"(document|pdf)\s+overview|"
    r"tl;?dr|"
    r"in\s+a\s+nutshell"
    r")\s*\??\s*$",
    re.I,
)

_INTRO_RE = re.compile(
    r"\b(abstract|introduction|intro|overview|preface|executive\s+summary|background)\b",
    re.I,
)
_OUTRO_RE = re.compile(
    r"\b(conclusion|conclusions|summary|closing|final\s+remarks|discussion|"
    r"future\s+work|acknowledgements?)\b",
    re.I,
)

_OVERVIEW_FORMAT = (
    "FORMAT=overview: 4–8 sentences summarizing what the document is about. "
    "Cover scope, main topics/sections, and any stated conclusion if present. "
    "Do not invent. Prefer 2–4 short quotes from different fetched pages. "
    "If only a sample of pages was fetched, say so briefly."
)


def is_overview_question(question: str) -> bool:
    """True only for whole-document overview asks (anchored match)."""
    q = (question or "").strip()
    if not q:
        return False
    return bool(_OVERVIEW_RE.match(q))


def select_overview_pages(
    headings: list[dict[str, Any]],
    *,
    page_count: int = 1,
) -> list[int]:
    """Pick up to 5 pages: intro/abstract, major section starts, conclusion.

    Documents without real headings: evenly sample across page_count.
    """
    for h in headings or []:
        for key in ("page_count", "end"):
            try:
                page_count = max(page_count, int(h.get(key) or 0))
            except (TypeError, ValueError):
                pass
    n = max(1, int(page_count or 1))

    real = [
        h
        for h in (headings or [])
        if str(h.get("title") or "").strip() not in ("", "(document)")
    ]
    if not real:
        if n == 1:
            return [1]
        fracs = [0.0, 0.25, 0.5, 0.75, 1.0]
        chosen: list[int] = []
        for f in fracs:
            p = max(1, min(n, int(round(1 + (n - 1) * f))))
            if p not in chosen:
                chosen.append(p)
            if len(chosen) >= _MAX_OVERVIEW_PAGES:
                break
        return chosen[:_MAX_OVERVIEW_PAGES]

    intro: list[int] = []
    outro: list[int] = []
    majors: list[int] = []

    min_level = min(int(h.get("level") or 1) for h in real)
    for h in real:
        title = str(h.get("title") or "")
        start = int(h.get("start") or 0)
        if start < 1:
            continue
        level = int(h.get("level") or 1)
        title_l = title.lower().strip()
        if title_l.startswith(("fig.", "figure", "table", "eq.")):
            continue
        if _INTRO_RE.search(title) and start not in intro:
            intro.append(start)
        if _OUTRO_RE.search(title) and start not in outro:
            outro.append(start)
        if level <= min_level and start not in majors:
            majors.append(start)

    chosen: list[int] = []

    def _add(page: int) -> None:
        if page >= 1 and page not in chosen and len(chosen) < _MAX_OVERVIEW_PAGES:
            chosen.append(page)

    for p in sorted(intro)[:2]:
        _add(p)
    if not chosen:
        _add(1)

    outro_pick = sorted(outro)[-1] if outro else None

    middle_slots = _MAX_OVERVIEW_PAGES - len(chosen) - (
        1 if outro_pick and outro_pick not in chosen else 0
    )
    middle_slots = max(0, middle_slots)
    if majors and middle_slots > 0:
        pool = [p for p in majors if p not in chosen]
        if len(pool) <= middle_slots:
            for p in pool:
                _add(p)
        else:
            step = (len(pool) - 1) / max(1, middle_slots - 1) if middle_slots > 1 else 0
            for i in range(middle_slots):
                idx = int(round(i * step)) if middle_slots > 1 else len(pool) // 2
                _add(pool[min(idx, len(pool) - 1)])

    if outro_pick is not None:
        _add(outro_pick)

    for p in majors:
        if len(chosen) >= _MAX_OVERVIEW_PAGES:
            break
        _add(p)

    if not chosen:
        chosen = [1]
    return chosen[:_MAX_OVERVIEW_PAGES]


_LIGHT_HEADING_CAP = 16

_LIGHT_SUMMARY_SYSTEM = """Role: document analyst. You write a brief orientation summary
from the document's table of contents / heading list only.

Rules:
- 2–4 short sentences about what the document appears to cover.
- Use only the supplied headings. Do not invent section content.
- Prefer concrete topic names from the headings.
- Prefer quote ids whose titles are at least a few words (avoid tiny titles).
- JSON only: {"status":"ok|insufficient_information","answer":"...","quotes":[{"id":"H1"}]}
- quotes must reference heading evidence IDs (H1, H2, …). Include 1–3 quotes.
"""


def _heading_quote_ok(title: str) -> bool:
    from app.agent.verifier import MIN_QUOTE_CHARS, _norm_for_match

    return len(_norm_for_match(title or "")) >= MIN_QUOTE_CHARS


def _sample_light_headings(headings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prefer quotable titles; sample across the TOC for long documents."""
    quotable = [
        h
        for h in headings
        if _heading_quote_ok(str(h.get("title") or "").strip())
    ]
    pool = quotable or list(headings)
    if len(pool) <= _LIGHT_HEADING_CAP:
        return pool
    n = len(pool)
    idxs = sorted(
        {
            0,
            n // 5,
            (2 * n) // 5,
            (3 * n) // 5,
            (4 * n) // 5,
            n - 1,
            *[
                int(round(i * (n - 1) / max(1, _LIGHT_HEADING_CAP - 1)))
                for i in range(_LIGHT_HEADING_CAP)
            ],
        }
    )
    picked: list[dict[str, Any]] = []
    for i in idxs:
        if len(picked) >= _LIGHT_HEADING_CAP:
            break
        h = pool[i]
        if h not in picked:
            picked.append(h)
    return picked[:_LIGHT_HEADING_CAP]


def run_light_summary(doc_id: str) -> dict[str, Any]:
    """
    Post-ingest light summary (budgeted, fast):

      list_headings → summarize from the first few heading titles (no get_page)
    """
    question = "What is this document about? (light TOC summary)"
    question_id = uuid.uuid4().hex[:12]
    start_deadline(REQUEST_DEADLINE_SEC)
    session = start_question(question_id, doc_id=doc_id)
    strategy = "light_summary"

    def _insufficient(reason: str, *, status_reason: str | None = None) -> dict[str, Any]:
        clear_active_session()
        clear_deadline()
        text, support = format_abstain_text(reason)
        return {
            "text": text,
            "status": "insufficient_information",
            "pages_used": [],
            "tool_trace": [r.as_dict() for r in session.trace],
            "calls_used": session.calls_used,
            "question_id": question_id,
            "reason": support,
            "status_reason": status_reason or reason,
            "intent": "overview",
            "strategy": strategy,
            "quotes": [],
        }

    try:
        try:
            headings = list_headings(doc_id)
        except BudgetExceededError:
            return _insufficient(
                "budget exceeded before headings", status_reason="budget_exhausted"
            )
        except Exception as exc:
            return _insufficient(
                f"list_headings failed: {type(exc).__name__}",
                status_reason="unreadable_document",
            )

        filtered = [
            h
            for h in (headings if isinstance(headings, list) else [])
            if str(h.get("title") or "").strip() not in ("", "(document)")
            and not str(h.get("title") or "")
            .lower()
            .startswith(("fig.", "figure", "table", "eq."))
        ]
        real = _sample_light_headings(filtered)

        if not real:
            return _insufficient("no headings available", status_reason="no_evidence")

        # Synthetic page bodies so heading titles can be verified as exact quotes.
        pages: dict[int, str] = {}
        lines: list[str] = []
        for i, h in enumerate(real, start=1):
            title = str(h.get("title") or "").strip()
            start = int(h.get("start") or 1)
            pages[start] = (pages.get(start) or "") + ("\n" if start in pages else "") + title
            lines.append(f"H{i} | page {start} | {title}")

        from app.llm.client import get_llm

        data = get_llm().complete_json(
            [
                {"role": "system", "content": _LIGHT_SUMMARY_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        "HEADING_EVIDENCE (id | page | title):\n"
                        + "\n".join(lines)
                        + "\n\nWrite a light orientation summary for a newly uploaded document."
                    ),
                },
            ],
            temperature=0.1,
            light=True,
            max_attempts=1,
        )

        status = str(data.get("status") or "insufficient_information").lower()
        answer = str(data.get("answer") or "").strip()
        if status != "ok" or not answer:
            return _insufficient(
                answer or "model declined light summary", status_reason="no_evidence"
            )

        id_to_heading = {f"H{i}": h for i, h in enumerate(real, start=1)}
        quotes: list[dict[str, Any]] = []
        for q in data.get("quotes") or []:
            if not isinstance(q, dict):
                continue
            ref = str(q.get("id") or q.get("ref") or "").strip().upper()
            h = id_to_heading.get(ref)
            if not h:
                continue
            title = str(h.get("title") or "").strip()
            start = int(h.get("start") or 1)
            if title and _heading_quote_ok(title):
                quotes.append({"text": title, "page": start})
            if len(quotes) >= 3:
                break

        if not quotes:
            for h in sorted(
                real,
                key=lambda x: len(str(x.get("title") or "").strip()),
                reverse=True,
            ):
                title = str(h.get("title") or "").strip()
                if _heading_quote_ok(title):
                    quotes = [
                        {"text": title, "page": int(h.get("start") or 1)}
                    ]
                    break

        if quotes:
            ok, failures = verify_quotes(quotes, pages)
            if not ok:
                # Drop short/bad cites; keep summary if any quote still verifies.
                kept: list[dict[str, Any]] = []
                for q in quotes:
                    q_ok, _ = verify_quotes([q], pages)
                    if q_ok:
                        kept.append(q)
                quotes = kept
            if not quotes:
                return _insufficient(
                    "quote verification failed: " + "; ".join(failures[:3]),
                    status_reason="invalid_output",
                )
        else:
            # All headings too short to cite — still return orientation text.
            quotes = []

        clear_active_session()
        clear_deadline()
        return {
            "text": answer,
            "status": "ok",
            "pages_used": sorted({int(h.get("start") or 1) for h in real}),
            "tool_trace": [r.as_dict() for r in session.trace],
            "calls_used": session.calls_used,
            "question_id": question_id,
            "quotes": quotes,
            "evidence_cleared": True,
            "intent": "overview",
            "strategy": strategy,
            "status_reason": None,
            "reason": f"Light TOC summary from {len(real)} headings (no page reads).",
        }
    except DeadlineExceededError:
        return _insufficient(
            "request deadline exceeded", status_reason="provider_timeout"
        )
    except Exception as exc:
        return _insufficient(
            f"light summary error: {type(exc).__name__}",
            status_reason="provider_unavailable",
        )


def run_overview(doc_id: str, question: str | None = None) -> dict[str, Any]:
    """
    Overview route (budgeted):

      list_headings → select intro/major/conclusion pages → get_page×≤5 → one answer
    """
    question = (question or "What is this document about?").strip()
    question_id = uuid.uuid4().hex[:12]
    start_deadline(REQUEST_DEADLINE_SEC)
    session = start_question(question_id, doc_id=doc_id)
    pages_used: list[int] = []
    fetched: dict[int, str] = {}
    strategy = "overview"
    page_count = 1

    def _insufficient(reason: str, *, status_reason: str | None = None) -> dict[str, Any]:
        fetched.clear()
        clear_active_session()
        clear_deadline()
        text, support = format_abstain_text(reason)
        return {
            "text": text,
            "status": "insufficient_information",
            "pages_used": sorted(set(pages_used)),
            "tool_trace": [r.as_dict() for r in session.trace],
            "calls_used": session.calls_used,
            "question_id": question_id,
            "reason": support,
            "status_reason": status_reason or reason,
            "intent": "overview",
            "strategy": strategy,
        }

    try:
        try:
            headings = list_headings(doc_id)
        except BudgetExceededError:
            return _insufficient(
                "budget exceeded before headings", status_reason="budget_exhausted"
            )
        except Exception as exc:
            return _insufficient(
                f"list_headings failed: {type(exc).__name__}",
                status_reason="unreadable_document",
            )

        heading_list = headings if isinstance(headings, list) else []
        for h in heading_list:
            try:
                page_count = max(page_count, int(h.get("page_count") or h.get("end") or 0))
            except (TypeError, ValueError):
                pass
        to_fetch = select_overview_pages(heading_list, page_count=page_count)
        to_fetch = to_fetch[: max(0, session.budget_left)]
        has_real_toc = any(
            str(h.get("title") or "").strip() not in ("", "(document)")
            for h in heading_list
        )
        coverage = (
            f"Sampled pages {to_fetch} of {page_count} "
            f"({'heading-guided' if has_real_toc else 'no TOC/headings; even sample'})."
        )

        for page_no in to_fetch:
            if session.budget_left < 1:
                break
            try:
                text = get_page(doc_id, page_no)
            except BudgetExceededError:
                return _insufficient(
                    "budget exceeded during get_page", status_reason="budget_exhausted"
                )
            except Exception:
                continue
            fetched[page_no] = text
            pages_used.append(page_no)

        if not fetched:
            return _insufficient("no pages fetched", status_reason="no_evidence")

        plan = {
            "rewritten": question,
            "qtype": "multi",
            "intent": "overview",
            "format_card": f"{_OVERVIEW_FORMAT} Coverage note: {coverage}",
            "keywords": [],
            "heading_hints": [],
            "contradiction_sensitive": False,
        }
        draft = draft_answer(
            question=question,
            plan=plan,
            pages=fetched,
            unused_candidates=[],
            budget_left=0,
        )

        if draft["status"] != "ok":
            detail = draft.get("error") or draft.get("answer") or "model declined"
            reason_code = "invalid_output" if draft.get("error") else "no_evidence"
            return _insufficient(str(detail), status_reason=reason_code)

        if not str(draft.get("answer") or "").strip():
            return _insufficient("empty answer", status_reason="invalid_output")

        quotes = list(draft.get("quotes") or [])
        ok, failures = verify_quotes(quotes, fetched)
        if not ok:
            from app.agent.evidence import repair_quotes

            repaired = repair_quotes(quotes, fetched)
            ok2, failures2 = verify_quotes(repaired, fetched)
            if not ok2:
                return _insufficient(
                    "quote verification failed: "
                    + "; ".join((failures2 or failures)[:3]),
                    status_reason="invalid_output",
                )
            quotes = repaired

        fetched.clear()
        clear_active_session()
        clear_deadline()
        return {
            "text": draft.get("answer") or "",
            "status": "ok",
            "pages_used": sorted(set(pages_used)),
            "tool_trace": [r.as_dict() for r in session.trace],
            "calls_used": session.calls_used,
            "question_id": question_id,
            "quotes": quotes,
            "evidence_cleared": True,
            "intent": "overview",
            "strategy": strategy,
            "status_reason": None,
            "reason": coverage,
        }
    except DeadlineExceededError:
        return _insufficient(
            "request deadline exceeded", status_reason="provider_timeout"
        )
    except Exception as exc:
        return _insufficient(
            f"overview error: {type(exc).__name__}",
            status_reason="provider_unavailable",
        )
