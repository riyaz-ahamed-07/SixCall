from __future__ import annotations

import uuid
from typing import Any

from app.config import REQUEST_DEADLINE_SEC
from app.deadline import DeadlineExceededError, clear_deadline, start_deadline
from app.agent.abstain import format_abstain_text
from app.agent.answerer import draft_answer
from app.agent.planner import plan_question
from app.agent.scorer import score_pages
from app.agent.verifier import verify_quotes
from app.tools.get_page import get_page
from app.tools.list_headings import list_headings
from app.tools.search_keyword import search_keyword
from app.tools.wrapper import (
    BudgetExceededError,
    clear_active_session,
    start_question,
)

_BROAD_HIT_CAP = 20
# Stop searching once this many calls remain so pages, not extra keywords, get them.
_PAGE_FLOOR = 3
_MAX_SEARCHES = 2
# Default read window, and the wider window for multi / compare / supersede.
_MAX_PAGES = 3
_MAX_PAGES_WIDE = 4


def _wide_read(plan: dict[str, Any], question: str = "") -> bool:
    """Multi/compare, or a question where a later statement can supersede an earlier one."""
    if plan.get("contradiction_sensitive") or plan.get("intent") in {"multi", "compare"}:
        return True
    blob = f"{question} {plan.get('rewritten') or ''}".lower()
    return any(k in blob for k in ("amend", "supersed"))


def select_initial_pages(
    ranked: list[int], budget_left: int, *, wide: bool
) -> list[int]:
    """Pages to read before the first answer.

    Default window is min(budget, 3). Multi/compare/supersede may use min(budget, 4).
    If candidates would remain and the last call would be spent, hold exactly one
    call for a repair get_page. Do not leave more than that one call idle.
    """
    if budget_left <= 0 or not ranked:
        return []
    limit = _MAX_PAGES_WIDE if wide else _MAX_PAGES
    slots = min(budget_left, limit, len(ranked))
    if len(ranked) > slots and budget_left - slots > 1:
        slots = min(len(ranked), budget_left - 1, _MAX_PAGES_WIDE)
    if (
        budget_left >= 2
        and len(ranked) > slots
        and budget_left - slots == 0
        and slots > 1
    ):
        slots -= 1
    return ranked[:slots]


def run_agent(doc_id: str, question: str) -> dict[str, Any]:
    """
    Tree + keyword agent.

    Budget math (the wrapper hard-stops the 7th call):
      1×list_headings + ≤2×search_keyword + ≤3–4×get_page ≤ 6

    Repair exists so a failed draft can spend one held-back get_page and
    re-draft once (two answer generations total, never a third).
    Follow-ups are off by default (SIXCALL_FOLLOWUPS=0): a live /ask must
    use these budgeted tools instead of answering from chat memory alone.
    """
    question_id = uuid.uuid4().hex[:12]
    start_deadline(REQUEST_DEADLINE_SEC)
    session = start_question(question_id, doc_id=doc_id)
    pages_used: list[int] = []
    fetched: dict[int, str] = {}
    evidence_cleared = False
    strategy = "tree+keyword"
    intent = None

    def _insufficient(reason: str, *, status_reason: str | None = None) -> dict[str, Any]:
        nonlocal evidence_cleared
        fetched.clear()
        evidence_cleared = True
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
            "intent": intent,
            "strategy": strategy,
        }

    try:
        if not (question or "").strip():
            return _insufficient("empty question", status_reason="no_evidence")

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

        plan = plan_question(question, headings)
        intent = plan.get("intent")
        if intent == "absent" and not plan.get("keywords"):
            return _insufficient(
                "planner marked absent with no keywords", status_reason="no_evidence"
            )

        # Preserve planner keyword order (most distinctive first).
        keywords = [str(k).strip() for k in (plan.get("keywords") or []) if str(k).strip()]
        wide = _wide_read(plan, question)

        keyword_hits: dict[str, list[int]] = {}
        for i, kw in enumerate(keywords):
            if i >= _MAX_SEARCHES:
                break
            # 1 heading + ≤2 searches, then the rest of the budget is for pages.
            if keyword_hits and session.budget_left <= _PAGE_FLOOR:
                break
            if session.budget_left < 1:
                break
            tight = [v for v in keyword_hits.values() if 0 < len(v) <= _BROAD_HIT_CAP]
            if (
                i > 0
                and tight
                and plan.get("intent") not in {"multi", "compare", "howto"}
                and not plan.get("contradiction_sensitive")
            ):
                break
            try:
                pages = search_keyword(doc_id, kw)
            except BudgetExceededError:
                return _insufficient(
                    "budget exceeded during search", status_reason="budget_exhausted"
                )
            except Exception:
                pages = []
            if not isinstance(pages, list) or any(not isinstance(p, int) for p in pages):
                pages = [int(p) for p in pages if str(p).isdigit()]
            if len(pages) > _BROAD_HIT_CAP and any(
                0 < len(v) <= _BROAD_HIT_CAP for v in keyword_hits.values()
            ):
                keyword_hits[kw] = []
            else:
                keyword_hits[kw] = pages

        if not any(keyword_hits.values()) and session.budget_left > _PAGE_FLOOR:
            for hint in plan.get("heading_hints") or []:
                if session.budget_left <= _PAGE_FLOOR:
                    break
                rescue = str(hint).strip()
                if len(rescue) < 3:
                    continue
                try:
                    pages = search_keyword(doc_id, rescue)
                except BudgetExceededError:
                    return _insufficient(
                        "budget exceeded during rescue search",
                        status_reason="budget_exhausted",
                    )
                except Exception:
                    pages = []
                if pages:
                    keyword_hits[rescue] = pages
                    break

        if not any(keyword_hits.values()):
            tree_pages = _heading_start_pages(headings, plan.get("heading_hints") or [])
            if not tree_pages:
                return _insufficient("empty search", status_reason="no_evidence")
            strategy = "tree-only"
            ranked = tree_pages[: max(1, session.budget_left)]
        else:
            # Use remaining budget for as many justified pages as possible.
            top_k = max(1, session.budget_left)
            ranked = score_pages(
                keyword_hits=keyword_hits,
                headings=headings,
                heading_hints=plan.get("heading_hints") or [],
                contradiction_sensitive=bool(plan.get("contradiction_sensitive")),
                top_k=top_k,
            )
            # Compare/multi: try to cover distinct keyword hit sets.
            if plan.get("intent") in {"multi", "compare", "howto"}:
                ranked = _ensure_coverage(ranked, keyword_hits, top_k)
            strategy = "tree+keyword"

        # Later statement supersedes earlier: lock max(keyword hits) in
        # before heading/tree boost can reorder the fetch window.
        latest_hit = _latest_keyword_page(keyword_hits) if _supersede(plan, question) else None
        if latest_hit is not None:
            ranked = [latest_hit, *[p for p in ranked if p != latest_hit]]

        tree_boost = _heading_start_pages(headings, plan.get("heading_hints") or [])
        preview = select_initial_pages(ranked, session.budget_left, wide=wide)
        if tree_boost:
            ranked = _apply_heading_boost(
                ranked,
                tree_boost,
                latest=latest_hit,
                window=max(1, len(preview) or 1),
            )

        if not ranked:
            return _insufficient("no candidate pages", status_reason="no_evidence")

        # Recompute after the boost so a newly inserted heading page can be read,
        # while the latest keyword hit stays inside the window.
        to_fetch = select_initial_pages(ranked, session.budget_left, wide=wide)
        for page_no in to_fetch:
            if session.budget_left < 1:
                break
            try:
                text = get_page(doc_id, page_no)
            except BudgetExceededError:
                return _insufficient(
                    "budget exceeded during get_page", status_reason="budget_exhausted"
                )
            except Exception as exc:
                return _insufficient(
                    f"get_page failed: {type(exc).__name__}",
                    status_reason="unreadable_document",
                )
            fetched[page_no] = text
            pages_used.append(page_no)

        if not fetched:
            return _insufficient("no pages fetched", status_reason="no_evidence")

        # Real remaining budget — not a hardcoded 0 — so the answerer can see
        # that one repair read may still be available.
        answer_calls = 0
        draft = _generate(question, plan, fetched, ranked, session.budget_left)
        answer_calls += 1
        quotes, detail, reason_code = _accept_draft(draft, fetched)
        unused = [p for p in ranked if p not in fetched]
        if (
            quotes is None
            and answer_calls < 2
            and session.budget_left >= 1
            and unused
        ):
            repair_page = unused[0]
            try:
                text = get_page(doc_id, repair_page)
            except BudgetExceededError:
                return _insufficient(
                    "budget exceeded during repair get_page",
                    status_reason="budget_exhausted",
                )
            except Exception as exc:
                return _insufficient(
                    f"get_page failed: {type(exc).__name__}",
                    status_reason="unreadable_document",
                )
            fetched[repair_page] = text
            pages_used.append(repair_page)
            draft = _generate(
                question, plan, fetched, ranked, session.budget_left
            )
            answer_calls += 1
            quotes, detail, reason_code = _accept_draft(draft, fetched)

        if quotes is None:
            return _insufficient(detail or "model declined", status_reason=reason_code)

        fetched.clear()
        evidence_cleared = True
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
            "evidence_cleared": evidence_cleared,
            "intent": intent,
            "strategy": strategy,
            "status_reason": None,
        }
    except DeadlineExceededError:
        return _insufficient(
            "request deadline exceeded", status_reason="provider_timeout"
        )
    except Exception as exc:
        return _insufficient(
            f"agent error: {type(exc).__name__}", status_reason="provider_unavailable"
        )


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
    """Return (quotes, detail, status_reason). quotes is None when not acceptable."""
    if draft.get("status") != "ok":
        detail = str(draft.get("error") or draft.get("answer") or "model declined")
        code = "invalid_output" if draft.get("error") else "no_evidence"
        return None, detail, code
    if not str(draft.get("answer") or "").strip():
        return None, "empty answer", "invalid_output"

    from app.agent.evidence import build_evidence_spans, repair_quotes

    quotes = list(draft.get("quotes") or [])
    spans = build_evidence_spans(pages)
    allowed = {str(s["id"]).upper() for s in spans}
    span_texts = {str(s["id"]).upper(): str(s["text"]) for s in spans}
    ok, failures = verify_quotes(
        quotes, pages, allowed_ids=allowed, span_texts=span_texts, spans=spans
    )
    if ok:
        return quotes, "", ""
    repaired = repair_quotes(quotes, pages)
    ok2, failures2 = verify_quotes(
        repaired, pages, allowed_ids=allowed, span_texts=span_texts, spans=spans
    )
    if ok2:
        return repaired, "", ""
    detail = "quote verification failed: " + "; ".join((failures2 or failures)[:3])
    return None, detail, "invalid_output"


def _supersede(plan: dict[str, Any], question: str) -> bool:
    if plan.get("contradiction_sensitive"):
        return True
    blob = f"{question} {plan.get('rewritten') or ''}".lower()
    return any(k in blob for k in ("amend", "supersed"))


def _latest_keyword_page(keyword_hits: dict[str, list[int]]) -> int | None:
    pages = [int(p) for hits in keyword_hits.values() for p in hits]
    return max(pages) if pages else None


def _apply_heading_boost(
    ranked: list[int],
    boost: list[int],
    *,
    latest: int | None,
    window: int,
) -> list[int]:
    """Insert heading starts into the fetch window without dropping `latest`.

    If the window is full, the lowest-priority non-latest page is replaced.
    """
    front = list(ranked[:window])
    rest = list(ranked[window:])
    for page in boost:
        if page in front:
            continue
        if len(front) < window:
            front.append(page)
            rest = [p for p in rest if p != page]
            continue
        victim = next((i for i in range(len(front) - 1, -1, -1) if front[i] != latest), None)
        if victim is None:
            if page not in rest:
                rest.append(page)
            continue
        displaced = front.pop(victim)
        front.append(page)
        rest = [p for p in rest if p != page]
        if displaced not in front and displaced not in rest:
            rest.append(displaced)
    return list(dict.fromkeys([*front, *rest]))


def _ensure_coverage(
    ranked: list[int], keyword_hits: dict[str, list[int]], top_k: int
) -> list[int]:
    """Ensure at least one page from each nonempty keyword hit set when possible."""
    chosen = list(ranked)
    for pages in keyword_hits.values():
        if not pages:
            continue
        if any(p in chosen for p in pages):
            continue
        pick = pages[0]
        if pick not in chosen:
            if len(chosen) >= top_k:
                chosen[-1] = pick
            else:
                chosen.append(pick)
    return chosen[:top_k]


def _heading_start_pages(
    headings: list[dict[str, Any]], hints: list[str]
) -> list[int]:
    pages: list[int] = []
    hints_l = [h.lower() for h in hints if h]
    for h in headings:
        title = str(h.get("title") or "").lower()
        if hints_l and any(hint in title or title in hint for hint in hints_l):
            start = int(h.get("start") or 1)
            if start not in pages:
                pages.append(start)
    return pages
