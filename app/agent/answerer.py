from __future__ import annotations

import logging
from typing import Any

from app.agent.evidence import build_evidence_spans, resolve_quote_refs
from app.llm.client import get_llm
from app.prompts.system import ANSWER_SYSTEM, build_answer_user


def draft_answer(
    *,
    question: str,
    plan: dict[str, Any],
    pages: dict[int, str],
    unused_candidates: list[int],
    budget_left: int,
) -> dict[str, Any]:
    spans = build_evidence_spans(pages)
    spans_by_id = {str(s["id"]).upper(): s for s in spans}
    messages = [
        {"role": "system", "content": ANSWER_SYSTEM},
        {
            "role": "user",
            "content": build_answer_user(
                question,
                pages,
                rewritten=str(plan.get("rewritten") or ""),
                qtype=str(plan.get("qtype") or ""),
                intent=str(plan.get("intent") or ""),
                format_card=str(plan.get("format_card") or ""),
                evidence_spans=spans,
            ),
        },
    ]

    try:
        # Judging profile: one provider attempt for the final answer generation.
        data = get_llm().complete_json(
            messages, temperature=0.1, light=True, max_attempts=1
        )
    except Exception as exc:
        logging.getLogger(__name__).warning("answer_generation_failed error=%s", type(exc).__name__)
        return {
            "status": "insufficient_information",
            "answer": "insufficient information",
            "quotes": [],
            "error": "Could not generate a valid answer. Please try the question again.",
        }

    status = str(data.get("status") or "insufficient_information").lower()
    if status not in {"ok", "insufficient_information"}:
        status = "insufficient_information"

    quotes = resolve_quote_refs(data.get("quotes") or [], spans_by_id)

    answer = str(data.get("answer") or "").strip()

    # status=ok requires a nonempty answer AND at least one quote.
    if status == "ok":
        if not answer:
            return {
                "status": "insufficient_information",
                "answer": "insufficient information",
                "quotes": [],
                "error": "empty_answer",
            }
        if not quotes:
            return {
                "status": "insufficient_information",
                "answer": "insufficient information",
                "quotes": [],
                "error": "missing_quotes",
            }

    if status == "insufficient_information" and not answer:
        answer = "insufficient information"

    return {
        "status": status,
        "answer": answer,
        "quotes": quotes if status == "ok" else [],
    }
