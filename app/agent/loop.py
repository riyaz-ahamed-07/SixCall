"""Structure-first ask loop.

Happy path (heading titles overlap the question): no planner model call.
  list_headings → question-only pins → search_keyword → get_page → one answer

A planner call happens only when that overlap is weak and a pin already hit
a page, so an absent question does not spend a model call. At most one
planner call, then at most one repair answer (two answer calls total).
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from typing import Any

from app.agent.abstain import format_abstain_text
from app.agent.answerer import draft_answer
from app.agent.evidence import build_evidence_spans
from app.agent.intent import attach_intent, resolve_intent
from app.agent.navigate import SectionMatch, choose_pages, match_sections, select_initial_pages
from app.agent.pins import extract_pins, term_in_question
from app.agent.planner import plan_question
from app.agent.verifier import verify_quotes
from app.config import REQUEST_DEADLINE_SEC
from app.deadline import DeadlineExceededError, clear_deadline, start_deadline
from app.tools.get_page import get_page
from app.tools.list_headings import list_headings
from app.tools.search_keyword import search_keyword
from app.tools.wrapper import BudgetExceededError, clear_active_session, start_question

logger = logging.getLogger(__name__)

_BROAD_HIT_CAP = 20
_PAGE_FLOOR = 3
_MAX_SEARCHES = 2
_SUPERSEDE_RE = re.compile(
    r"\b(amend\w*|supersed\w*|latest|revised|replaced|current)\b",
    re.I,
)


def run_agent(doc_id: str, question: str) -> dict[str, Any]:
    question_id = uuid.uuid4().hex[:12]
    started = time.perf_counter()
    start_deadline(REQUEST_DEADLINE_SEC)
    session = start_question(question_id, doc_id=doc_id)
    pages_used: list[int] = []
    fetched: dict[int, str] = {}
    evidence_cleared = False
    strategy = "section"
    intent = None
    planner_ms = 0.0
    answer_ms = 0.0
    llm_calls = 0
    planner_used = False

    def _timing() -> dict[str, Any]:
        tool_ms = round(sum(float(getattr(r, "elapsed_ms", 0.0) or 0.0) for r in session.trace), 3)
        llm_ms = round(planner_ms + answer_ms, 3)
        return {
            "tool_ms": tool_ms,
            "llm_ms": llm_ms,
            "planner_ms": round(planner_ms, 3),
            "answer_ms": round(answer_ms, 3),
            "total_ms": round((time.perf_counter() - started) * 1000, 3),
            "llm_calls": llm_calls,
            "planner_used": planner_used,
        }

    def _insufficient(reason: str, *, status_reason: str | None = None) -> dict[str, Any]:
        nonlocal evidence_cleared
        fetched.clear()
        evidence_cleared = True
        timing = _timing()
        clear_active_session()
        clear_deadline()
        text, support = format_abstain_text(reason)
        logger.info(
            "ask_timing qid=%s status=insufficient tool_ms=%s llm_ms=%s llm_calls=%s planner=%s calls=%s",
            question_id,
            timing["tool_ms"],
            timing["llm_ms"],
            timing["llm_calls"],
            planner_used,
            session.calls_used,
        )
        return {
            "text": text,
            "status": "insufficient_information",
            "pages_used": sorted(set(pages_used)),
            "tool_trace": [r.as_dict() for r in session.trace],
            "calls_used": session.calls_used,
            "question_id": question_id,
            "reason": support,
            "status_reason": status_reason or reason,
            "intent": intent,
            "strategy": strategy,
            "timing": timing,
            "evidence_cleared": evidence_cleared,
        }

    try:
        if not (question or "").strip():
            return _insufficient("empty question", status_reason="no_evidence")

        try:
            headings = list_headings(doc_id)
        except BudgetExceededError:
            return _insufficient("budget exceeded before headings", status_reason="budget_exhausted")
        except Exception as exc:
            return _insufficient(
                f"list_headings failed: {type(exc).__name__}",
                status_reason="unreadable_document",
            )

        pins = extract_pins(question)
        sections = match_sections(question, headings)
        supersede = bool(_SUPERSEDE_RE.search(question or ""))
        intent = resolve_intent(question)
        wide = supersede or intent in {"multi", "compare"}
        plan = _local_plan(question, pins, sections, supersede=supersede)
        intent = plan.get("intent")

        keyword_hits: dict[str, list[int]] = {}
        searched: set[str] = set()
        for pin in pins:
            if len(searched) >= _MAX_SEARCHES:
                break
            if keyword_hits and session.budget_left <= _PAGE_FLOOR:
                break
            if session.budget_left < 1:
                break
            tight = [v for v in keyword_hits.values() if 0 < len(v) <= _BROAD_HIT_CAP]
            if tight and not wide and len(searched) >= 1:
                break
            pages = _search(doc_id, pin)
            if pages is None:
                return _insufficient("budget exceeded during search", status_reason="budget_exhausted")
            searched.add(pin.lower())
            if len(pages) > _BROAD_HIT_CAP and any(
                0 < len(v) <= _BROAD_HIT_CAP for v in keyword_hits.values()
            ):
                keyword_hits[pin] = []
            else:
                keyword_hits[pin] = pages

        has_hits = any(keyword_hits.values())
        real_headings = [
            h for h in headings if str(h.get("title") or "").strip() and not str(h.get("title")).startswith("(")
        ]
        if not sections.strong and has_hits and real_headings:
            t0 = time.perf_counter()
            try:
                planned = plan_question(question, headings)
            except Exception:
                planned = None
            planner_ms += (time.perf_counter() - t0) * 1000
            llm_calls += 1
            planner_used = True
            if isinstance(planned, dict):
                plan = _constrain_plan(planned, question, headings, pins, supersede=supersede)
                intent = plan.get("intent")
                sections = _merge_hints(sections, headings, plan.get("heading_hints") or [])
                supersede = supersede or bool(plan.get("contradiction_sensitive"))
                wide = supersede or intent in {"multi", "compare"}

        if not has_hits and not sections.starts:
            return _insufficient("empty search", status_reason="no_evidence")

        if has_hits:
            strategy = "section+pin" if sections.strong or sections.starts else "pin"
        else:
            strategy = "section"

        window = min(session.budget_left, 4 if wide else 3)
        ranked = choose_pages(
            keyword_hits=keyword_hits,
            sections=sections,
            supersede=supersede,
            ensure_each_hit=intent in {"multi", "compare"},
            top_k=max(1, window),
        )
        if not ranked and sections.starts:
            ranked = list(sections.starts)

        if not ranked:
            return _insufficient("no candidate pages", status_reason="no_evidence")

        to_fetch = select_initial_pages(ranked, session.budget_left, wide=wide)
        if not _fetch_pages(doc_id, to_fetch, fetched, pages_used, session):
            return _insufficient("budget exceeded during get_page", status_reason="budget_exhausted")
        if not fetched:
            return _insufficient("no pages fetched", status_reason="no_evidence")

        answer_calls = 0
        t0 = time.perf_counter()
        draft = _generate(question, plan, fetched, ranked, session.budget_left)
        answer_ms += (time.perf_counter() - t0) * 1000
        llm_calls += 1
        answer_calls += 1
        quotes, detail, reason_code = _accept_draft(draft, fetched)
        unused = [p for p in ranked if p not in fetched]
        if quotes is None and answer_calls < 2 and session.budget_left >= 1 and unused:
            if not _fetch_pages(doc_id, [unused[0]], fetched, pages_used, session):
                return _insufficient(
                    "budget exceeded during repair get_page",
                    status_reason="budget_exhausted",
                )
            t1 = time.perf_counter()
            draft = _generate(question, plan, fetched, ranked, session.budget_left)
            answer_ms += (time.perf_counter() - t1) * 1000
            llm_calls += 1
            answer_calls += 1
            quotes, detail, reason_code = _accept_draft(draft, fetched)

        if quotes is None:
            return _insufficient(detail or "model declined", status_reason=reason_code)

        timing = _timing()
        fetched.clear()
        evidence_cleared = True
        clear_active_session()
        clear_deadline()
        logger.info(
            "ask_timing qid=%s status=ok tool_ms=%s llm_ms=%s llm_calls=%s planner=%s calls=%s",
            question_id,
            timing["tool_ms"],
            timing["llm_ms"],
            timing["llm_calls"],
            planner_used,
            session.calls_used,
        )
        return {
            "text": draft.get("answer") or "",
            "status": "ok",
            "pages_used": sorted(set(pages_used)),
            "tool_trace": [r.as_dict() for r in session.trace],
            "calls_used": session.calls_used,
            "question_id": question_id,
            "quotes": quotes,
            "evidence_cleared": evidence_cleared,
            "intent": intent,
            "strategy": strategy,
            "status_reason": None,
            "timing": timing,
        }
    except DeadlineExceededError:
        return _insufficient("request deadline exceeded", status_reason="provider_timeout")
    except Exception as exc:
        return _insufficient(f"agent error: {type(exc).__name__}", status_reason="provider_unavailable")


def _local_plan(
    question: str,
    pins: list[str],
    sections: SectionMatch,
    *,
    supersede: bool,
) -> dict[str, Any]:
    plan = {
        "rewritten": question.strip(),
        "qtype": "fact",
        "keywords": list(pins),
        "heading_hints": sections.titles[:4],
        "contradiction_sensitive": supersede,
    }
    return attach_intent(plan, question)


def _constrain_plan(
    planned: dict[str, Any],
    question: str,
    headings: list[dict[str, Any]],
    pins: list[str],
    *,
    supersede: bool,
) -> dict[str, Any]:
    """Drop any planner keyword that is not a substring of the question."""
    keywords = [
        str(k).strip()
        for k in (planned.get("keywords") or [])
        if str(k).strip() and term_in_question(str(k), question)
    ]
    if not keywords:
        keywords = list(pins)
    known = {str(h.get("title") or "").strip(): str(h.get("title") or "").strip() for h in headings}
    hints: list[str] = []
    for hint in planned.get("heading_hints") or []:
        hint_s = str(hint).strip()
        if not hint_s:
            continue
        for title in known.values():
            if hint_s.lower() == title.lower() or hint_s.lower() in title.lower():
                if title not in hints:
                    hints.append(title)
                break
    plan = {
        "rewritten": question.strip(),
        "qtype": str(planned.get("qtype") or "fact"),
        "keywords": keywords[:4],
        "heading_hints": hints[:4],
        "contradiction_sensitive": supersede or bool(planned.get("contradiction_sensitive")),
    }
    return attach_intent(plan, question)


def _merge_hints(
    sections: SectionMatch,
    headings: list[dict[str, Any]],
    hints: list[str],
) -> SectionMatch:
    if not hints:
        return sections
    hint_l = [h.lower() for h in hints if h]
    merged = list(sections.headings)
    have = {str(h.get("title") or "").lower() for h in merged}
    for heading in headings:
        title = str(heading.get("title") or "")
        title_l = title.lower()
        if not title or title_l in have:
            continue
        if any(hint in title_l or title_l in hint for hint in hint_l):
            merged.append(heading)
            have.add(title_l)
    ranges: list[tuple[int, int]] = []
    starts: list[int] = []
    for heading in merged:
        start = int(heading.get("start") or 1)
        end = int(heading.get("end") or start)
        if end < start:
            end = start
        ranges.append((start, end))
        if start not in starts:
            starts.append(start)
    return SectionMatch(strong=sections.strong or bool(merged), headings=merged, ranges=ranges, starts=starts)


def _search(doc_id: str, pin: str) -> list[int] | None:
    """Return page numbers, [] on a tool error, or None when the budget is spent."""
    try:
        pages = search_keyword(doc_id, pin)
    except BudgetExceededError:
        return None
    except Exception:
        return []
    if not isinstance(pages, list):
        return [int(p) for p in pages if str(p).isdigit()]
    out: list[int] = []
    for page in pages:
        if isinstance(page, int) and not isinstance(page, bool):
            out.append(page)
    return out


def _fetch_pages(
    doc_id: str,
    page_numbers: list[int],
    fetched: dict[int, str],
    pages_used: list[int],
    session: Any,
) -> bool:
    """False when the budget wrapper refuses a call. Other read errors skip that page."""
    for page_no in page_numbers:
        if page_no in fetched:
            continue
        if session.budget_left < 1:
            return False
        try:
            text = get_page(doc_id, page_no)
        except BudgetExceededError:
            return False
        except Exception:
            continue
        fetched[int(page_no)] = text
        pages_used.append(int(page_no))
    return True


def _generate(
    question: str,
    plan: dict[str, Any],
    fetched: dict[int, str],
    ranked: list[int],
    budget_left: int,
) -> dict[str, Any]:
    unused = [p for p in ranked if p not in fetched]
    return draft_answer(
        question=question,
        plan=plan,
        pages=fetched,
        unused_candidates=unused,
        budget_left=budget_left,
    )


def _accept_draft(
    draft: dict[str, Any], pages: dict[int, str]
) -> tuple[list[dict[str, Any]] | None, str, str]:
    if draft.get("status") != "ok":
        detail = str(draft.get("error") or draft.get("answer") or "model declined")
        code = "invalid_output" if draft.get("error") else "no_evidence"
        return None, detail, code
    if not str(draft.get("answer") or "").strip():
        return None, "empty answer", "invalid_output"
    quotes = list(draft.get("quotes") or [])
    spans = build_evidence_spans(pages)
    allowed = {str(s["id"]).upper() for s in spans}
    span_texts = {str(s["id"]).upper(): str(s["text"]) for s in spans}
    ok, failures = verify_quotes(
        quotes, pages, allowed_ids=allowed, span_texts=span_texts, spans=spans
    )
    if ok:
        return quotes, "", ""
    detail = "quote verification failed: " + "; ".join(failures[:3])
    return None, detail, "invalid_output"
