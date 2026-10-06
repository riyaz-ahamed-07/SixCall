"""Structure-first ask loop.

Structure-first means a TOC walk through the allowed list_headings tool,
not semantic retrieval. Never call this RAG, vectorless RAG, or PageIndex.

Judge one-liner: navigate section tree + pin question entities + hard 6-call
ledger + fail-closed evidence IDs.

Happy path (heading titles overlap the question): 0 planner LLM calls.
  list_headings → question-only pins → one search_keyword(pins) → get_page → one answer

A TOC-pick model call is optional and only when overlap is weak, a pin
already hit a page, and the outline has real headings. It may choose only
existing titles or node ids, and use_terms must be a subset of the question
extract. At most one such call. Read selected evidence before the single
final answer generation; failed verification abstains without a redraft.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from app.agent.abstain import format_abstain_text
from app.agent.answerer import draft_answer
from app.agent.evidence import build_evidence_spans
from app.agent.intent import attach_intent, resolve_intent
from app.agent.navigate import (
    SectionMatch,
    apply_supersede_lock,
    choose_pages,
    match_sections,
    select_initial_pages,
)
from app.agent.pins import extract_question, term_allowed
from app.agent.schemas import AskResult, Plan
from app.agent.toc_pick import accept_toc_pick, pick_toc
from app.agent.verifier import verify_quotes
from app.config import REQUEST_DEADLINE_SEC
from app.deadline import DeadlineExceededError, clear_deadline, start_deadline
from app.logging_setup import short, step
from app.tools.get_page import get_page
from app.tools.list_headings import list_headings
from app.tools.search_keyword import search_keyword
from app.tools.wrapper import BudgetExceededError, clear_active_session, start_question

logger = logging.getLogger(__name__)

_FEW_HEADINGS = 3


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

    step(
        "AGENT",
        "START",
        qid=question_id,
        doc=doc_id,
        budget=session.max_calls,
        q=short(question),
    )

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
            "planner_llm": 1 if planner_used else 0,
            "toc_llm": 1 if planner_used else 0,
        }

    def _insufficient(reason: str, *, status_reason: str | None = None) -> dict[str, Any]:
        nonlocal evidence_cleared
        fetched.clear()
        evidence_cleared = True
        timing = _timing()
        clear_active_session()
        clear_deadline()
        text, support = format_abstain_text(reason)
        step(
            "AGENT",
            "DONE insufficient",
            qid=question_id,
            reason=short(reason, limit=120),
            status_reason=status_reason or reason,
            calls=f"{session.calls_used}/{session.max_calls}",
            strategy=strategy,
            elapsed_ms=timing["total_ms"],
        )
        return _pack(
            {
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
        )

    try:
        if not (question or "").strip():
            return _insufficient("empty question", status_reason="no_evidence")

        step("AGENT", "step=list_headings")
        try:
            headings = list_headings(doc_id)
        except BudgetExceededError:
            return _insufficient("budget exceeded before headings", status_reason="budget_exhausted")
        except Exception as exc:
            return _insufficient(
                f"list_headings failed: {type(exc).__name__}",
                status_reason="unreadable_document",
            )
        step("AGENT", "step=list_headings ok", count=len(headings or []))

        extract = extract_question(question)
        pins = extract.terms[:4]
        sections = match_sections(question, headings, extract.terms)
        supersede = extract.supersede
        intent = resolve_intent(question)
        wide = supersede or intent in {"multi", "compare"}
        plan = _local_plan(question, pins, sections, supersede=supersede)
        intent = plan.get("intent")
        real_headings = [
            h
            for h in headings
            if str(h.get("title") or "").strip() and not str(h.get("title")).startswith("(")
        ]
        step(
            "AGENT",
            "step=plan",
            pins=pins,
            intent=intent,
            section_hits=len(sections.starts or []),
            strong=bool(sections.strong),
            supersede=bool(supersede),
        )
        # Budget: 1×list_headings + 1×search_keyword(pins) + ≤4×get_page ≤ 6.
        keyword_hits: dict[str, list[int]] = {}
        step("AGENT", "step=search_keyword", pins=pins)
        pages = _search_pins_once(doc_id, pins, extract)
        if pages is None:
            return _insufficient("budget exceeded during search", status_reason="budget_exhausted")
        if pages:
            keyword_hits["pins"] = pages
        step("AGENT", "step=search_keyword ok", pages=pages[:12] if pages else [])

        has_hits = any(keyword_hits.values())
        # Strong overlap: planner_llm=0. A TOC pick is optional and only when
        # the outline did not match and a pin already hit a page.
        if sections.strong:
            step("AGENT", "step=toc_pick skip", reason="strong_section_match", planner_llm=0)
        elif has_hits and real_headings:
            step("AGENT", "step=toc_pick …")
            t0 = time.perf_counter()
            try:
                picked = pick_toc(question, headings, extract.terms)
            except Exception:
                picked = None
            planner_ms += (time.perf_counter() - t0) * 1000
            llm_calls += 1
            planner_used = True
            accepted = accept_toc_pick(
                picked if isinstance(picked, dict) else {},
                headings,
                extract.terms,
            )
            sections = _apply_toc(sections, accepted.get("headings") or [])
            plan = _local_plan(question, pins, sections, supersede=supersede)
            intent = plan.get("intent")
            step(
                "AGENT",
                "step=toc_pick ok",
                headings=[str(h.get("title") or "") for h in (accepted.get("headings") or [])][:3],
                planner_ms=planner_ms,
            )
            # use_terms are a subset of the question extract; already covered
            # by the single multi-pin search above.

        has_hits = any(keyword_hits.values())
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
        # Multi-pin search already ranked by co-occurrence; keep that order
        # ahead of pure section starts when both exist.
        if pages:
            ranked = list(dict.fromkeys([*pages, *ranked]))
        if not ranked and sections.starts:
            ranked = list(sections.starts)

        if not ranked:
            return _insufficient("no candidate pages", status_reason="no_evidence")

        to_fetch = select_initial_pages(ranked, session.budget_left, wide=wide)
        hit_pages = [page for hit in keyword_hits.values() for page in hit]
        latest = max(hit_pages) if supersede and hit_pages else None
        to_fetch = apply_supersede_lock(to_fetch, latest)
        step(
            "AGENT",
            "step=fetch",
            strategy=strategy,
            ranked=ranked[:10],
            to_fetch=to_fetch,
            budget_left=session.budget_left,
        )
        if not _fetch_pages(doc_id, to_fetch, fetched, pages_used, session):
            return _insufficient("budget exceeded during get_page", status_reason="budget_exhausted")
        if not fetched:
            return _insufficient("no pages fetched", status_reason="no_evidence")
        step("AGENT", "step=fetch ok", pages=sorted(fetched.keys()))

        step("AGENT", "step=answer …")
        t0 = time.perf_counter()
        draft = _generate(question, plan, fetched, ranked, session.budget_left)
        answer_ms += (time.perf_counter() - t0) * 1000
        llm_calls += 1
        quotes, detail, reason_code = _accept_draft(draft, fetched)
        if quotes is None:
            step(
                "AGENT",
                "step=verify FAIL",
                reason=short(detail or "model declined", limit=120),
                code=reason_code,
            )
            return _insufficient(detail or "model declined", status_reason=reason_code)
        step("AGENT", "step=verify ok", quotes=len(quotes), answer_ms=answer_ms)

        timing = _timing()
        fetched.clear()
        evidence_cleared = True
        clear_active_session()
        clear_deadline()
        step(
            "AGENT",
            "DONE ok",
            qid=question_id,
            calls=f"{session.calls_used}/{session.max_calls}",
            pages=sorted(set(pages_used)),
            strategy=strategy,
            tool_ms=timing["tool_ms"],
            llm_ms=timing["llm_ms"],
            elapsed_ms=timing["total_ms"],
        )
        return _pack(
            {
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
        )
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
    return Plan.model_validate(attach_intent(plan, question)).model_dump()


def _apply_toc(sections: SectionMatch, chosen: list[dict[str, Any]]) -> SectionMatch:
    """Union TOC-picked headings into the ranges. Cap stays at three."""
    if not chosen:
        return sections
    merged = list(sections.headings)
    have = {str(h.get("title") or "").lower() for h in merged}
    for heading in chosen:
        title = str(heading.get("title") or "").strip()
        if not title or title.lower() in have:
            continue
        merged.append(heading)
        have.add(title.lower())
    merged = merged[:3]
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
    return SectionMatch(strong=True, headings=merged, ranges=ranges, starts=starts)


def _pack(payload: dict[str, Any]) -> dict[str, Any]:
    """Fail closed if an ask result does not match the public shape."""
    try:
        return AskResult.model_validate(payload).model_dump()
    except Exception:
        return {
            "text": "insufficient information",
            "status": "insufficient_information",
            "pages_used": [],
            "tool_trace": [],
            "calls_used": int(payload.get("calls_used") or 0),
            "question_id": str(payload.get("question_id") or ""),
            "reason": "invalid_output",
            "status_reason": "invalid_output",
            "quotes": [],
            "intent": None,
            "strategy": None,
            "timing": None,
            "evidence_cleared": True,
        }


def _search_pins_once(
    doc_id: str,
    pins: list[str],
    extract: Any,
) -> list[int] | None:
    """One search_keyword call over all allowed pins. None = budget refused."""
    allowed = [pin for pin in pins if term_allowed(pin, extract)]
    if not allowed:
        return []
    try:
        pages = search_keyword(doc_id, allowed if len(allowed) > 1 else allowed[0])
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
    return None, detail, "quote_mismatch"
