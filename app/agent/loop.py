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
# Keep enough budget for evidence reads after search.
_MIN_PAGE_RESERVE = 1
_MIN_PAGE_RESERVE_CODING = 3
# Cap page reads — more pages = bigger answer prompt = slower demos.
_MAX_PAGES_FETCH = 2
_MAX_PAGES_FETCH_HOWTO = 3
_MAX_SEARCHES_CODING = 2


def _pages_fetch_cap(intent: str | None) -> int:
    if intent in {"howto", "multi"}:
        return _MAX_PAGES_FETCH_HOWTO
    return _MAX_PAGES_FETCH


def _page_reserve(plan: dict[str, Any]) -> int:
    if plan.get("coding") or plan.get("intent") == "howto":
        return _MIN_PAGE_RESERVE_CODING
    return _MIN_PAGE_RESERVE


def run_agent(doc_id: str, question: str) -> dict[str, Any]:
    """
    Tree + keyword agent (budgeted):

      list_headings → plan → search_keyword → score → get_page(s) → ONE answer → verify
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
        page_reserve = _page_reserve(plan)
        max_searches = (
            _MAX_SEARCHES_CODING
            if plan.get("coding") or plan.get("intent") == "howto"
            else len(keywords)
        )

        keyword_hits: dict[str, list[int]] = {}
        for i, kw in enumerate(keywords):
            if i >= max_searches:
                break
            # Reserve slots for page reads before spending on another search.
            if session.budget_left <= page_reserve and keyword_hits:
                break
            if session.budget_left < 1:
                break
            tight = [v for v in keyword_hits.values() if 0 < len(v) <= _BROAD_HIT_CAP]
            if (
                i > 0
                and tight
                and plan.get("intent") not in {"multi", "compare", "howto"}
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

        if not any(keyword_hits.values()) and session.budget_left > page_reserve:
            for hint in plan.get("heading_hints") or []:
                if session.budget_left <= page_reserve:
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

        # Outline section starts — append after keyword ranks so rare hits (e.g. CSV) win.
        tree_boost = _heading_start_pages(headings, plan.get("heading_hints") or [])
        if tree_boost:
            ranked = list(dict.fromkeys([*ranked, *tree_boost]))[
                : max(1, session.budget_left)
            ]

        if not ranked:
            return _insufficient("no candidate pages", status_reason="no_evidence")

        fetch_cap = min(session.budget_left, _pages_fetch_cap(plan.get("intent")))
        to_fetch = _expand_neighbor_pages(
            ranked[:fetch_cap],
            ranked,
            max_total=fetch_cap,
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
            except Exception as exc:
                return _insufficient(
                    f"get_page failed: {type(exc).__name__}",
                    status_reason="unreadable_document",
                )
            fetched[page_no] = text
            pages_used.append(page_no)

        if not fetched:
            return _insufficient("no pages fetched", status_reason="no_evidence")

        # ONE final generation — no reserve redraft, no quote-repair LLM.
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


def _expand_neighbor_pages(
    chosen: list[int],
    pool: list[int],
    *,
    max_total: int,
) -> list[int]:
    """Pull adjacent pages from the ranked pool (code/samples often span page breaks)."""
    if max_total < 1 or not chosen:
        return chosen[:max_total]
    pool_set = set(pool)
    out = list(chosen)
    for p in chosen:
        if len(out) >= max_total:
            break
        for n in (p + 1, p - 1):
            if n in pool_set and n not in out:
                out.append(n)
                break
    return out[:max_total]


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
