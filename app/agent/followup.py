from __future__ import annotations

import re
import uuid
from typing import Any

from app.agent.abstain import format_abstain_text
from app.deadline import clear_deadline, start_deadline
from app.config import REQUEST_DEADLINE_SEC
from app.llm.client import get_llm

# Only pure clarifications of the previous answer. A new question uses tools.
_PURE_CLARIFY = re.compile(
    r"^\s*("
    r"why\??"
    r"|how\s+so\??"
    r"|meaning\??"
    r"|again\??"
    r"|go\s+on\??"
    r"|continue\??"
    r"|in\s+other\s+words\??"
    r"|(?:simpler|shorter|longer)(?:\s+please)?\??"
    r"|(?:please\s+)?(?:explain|clarify|elaborate|expand)"
    r"(?:\s+(?:that|this|it|more|further))+"
    r"(?:\s+(?:simply|more|further|a\s+bit))?\??"
    r"|which\s+page(?:\s+\w+){0,6}\??"
    r")\s*$",
    re.I,
)

_NEW_TOPIC = re.compile(
    r"\b("
    r"what\s+is\s+(the|a|an)\s+\w|"
    r"how\s+(to|do|does|can|should)\b|"
    r"define\s+|prove\s+|compare\s+|find\s+|search\s+|look\s+up|"
    r"on\s+page\s+\d+|section\s+\d+|according\s+to\s+the\s+document|"
    r"does\s+(the\s+)?(document|pdf|policy)\s+"
    r")\b",
    re.I,
)

_ABSTAIN_TEXT = re.compile(
    r"^\s*(insufficient information|follow-?up needs a new document lookup)\s*$",
    re.I,
)

FOLLOWUP_SYSTEM = """Role: conversational assistant for a document Q&A product.

You answer follow-up questions using ONLY the prior turns in this chat
(PRIOR_CONTEXT). Do not invent new document facts. Do not claim you read
new pages. If the follow-up needs information not present in PRIOR_CONTEXT,
set status to insufficient_information and say a new document lookup is required.

PRIOR_CONTEXT is prior user questions and assistant answers (with any quotes
already shown). It is conversation memory, not a fresh document read.

status=ok requires quotes copied verbatim from PRIOR_CONTEXT QUOTE lines.
If the follow-up needs any new document fact, set status to insufficient_information.

JSON only:
{"status":"ok|insufficient_information","answer":"...","quotes":[{"text":"exact prior quote","page":1}]}
"""


def _last_assistant_turn(history: list[dict[str, Any]]) -> dict[str, Any] | None:
    for turn in reversed(history):
        if str(turn.get("role") or "") == "assistant" and str(turn.get("text") or "").strip():
            return turn
    return None


def prior_answer_was_insufficient(history: list[dict[str, Any]] | None) -> bool:
    """True when the last assistant reply abstained / has no usable evidence."""
    last = _last_assistant_turn(list(history or []))
    if last is None:
        return True
    status = str(last.get("status") or "").lower()
    if status == "insufficient_information":
        return True
    text = str(last.get("text") or "").strip()
    if _ABSTAIN_TEXT.match(text):
        return True
    if not (last.get("quotes") or []):
        # Abstains never carry quotes; successful answers always do.
        if "insufficient" in text.lower() or "new document lookup" in text.lower():
            return True
    return False


def is_followup_question(question: str, history: list[dict[str, Any]] | None) -> bool:
    """True only for a short clarification of the previous answer.

    Normal questions, including ones asked in an existing chat, always take
    the tool path. Zero-tool replies are not used for a new lookup.
    """
    if not history:
        return False
    if prior_answer_was_insufficient(history):
        return False

    q = (question or "").strip()
    if not q or len(q.split()) > 12:
        return False
    if _NEW_TOPIC.search(q):
        return False
    return bool(_PURE_CLARIFY.match(q))


def _prior_quote_pages(history: list[dict[str, Any]]) -> dict[int, str]:
    pages: dict[int, str] = {}
    for turn in history:
        for q in turn.get("quotes") or []:
            if not isinstance(q, dict):
                continue
            text = str(q.get("text") or "").strip()
            try:
                page = int(q.get("page"))
            except (TypeError, ValueError):
                continue
            if not text:
                continue
            prev = pages.get(page, "")
            pages[page] = f"{prev}\n{text}".strip() if prev else text
    return pages


def run_followup(
    doc_id: str,
    question: str,
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Follow-up path: zero document tools. One LLM reply from prior chat context.
    """
    question_id = uuid.uuid4().hex[:12]
    start_deadline(REQUEST_DEADLINE_SEC)
    strategy = "followup"

    def _done(
        *,
        text: str,
        status: str,
        reason: str | None = None,
        status_reason: str | None = None,
        quotes: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        clear_deadline()
        return {
            "text": text,
            "status": status,
            "pages_used": [],
            "tool_trace": [],
            "calls_used": 0,
            "question_id": question_id,
            "reason": reason,
            "status_reason": status_reason,
            "quotes": list(quotes or []),
            "intent": "followup",
            "strategy": strategy,
        }

    try:
        context_lines: list[str] = []
        # Keep last few turns only (bounded context)
        recent = history[-8:]
        for turn in recent:
            role = str(turn.get("role") or "user")
            text = str(turn.get("text") or "").strip()
            if not text:
                continue
            label = "USER" if role == "user" else "ASSISTANT"
            context_lines.append(f"{label}: {text}")
            quotes = turn.get("quotes") or []
            if isinstance(quotes, list) and quotes:
                for q in quotes[:4]:
                    if not isinstance(q, dict):
                        continue
                    qt = str(q.get("text") or "").strip()
                    qp = q.get("page")
                    if qt:
                        context_lines.append(f'  QUOTE p.{qp}: "{qt}"')

        messages = [
            {"role": "system", "content": FOLLOWUP_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"DOC_ID: {doc_id}\n"
                    f"PRIOR_CONTEXT:\n"
                    + ("\n".join(context_lines) or "(none)")
                    + f"\n\nFOLLOW_UP: {question}"
                ),
            },
        ]
        data = get_llm().complete_json(messages, temperature=0.1, light=False)
        status = str(data.get("status") or "insufficient_information").lower()
        if status not in {"ok", "insufficient_information"}:
            status = "insufficient_information"
        answer = str(data.get("answer") or "").strip()
        if status == "ok" and not answer:
            return _done(
                text="insufficient information",
                status="insufficient_information",
                reason="empty follow-up answer",
                status_reason="invalid_output",
            )
        if status == "ok":
            from app.agent.verifier import verify_quotes

            prior_pages = _prior_quote_pages(history)
            raw_quotes = [
                q for q in (data.get("quotes") or []) if isinstance(q, dict)
            ]
            ok, failures = verify_quotes(raw_quotes, prior_pages)
            if not ok:
                return _done(
                    text="insufficient information",
                    status="insufficient_information",
                    reason="follow-up quote was not in prior evidence: "
                    + "; ".join(failures[:2]),
                    status_reason="invalid_output",
                )
            return _done(text=answer, status="ok", quotes=raw_quotes)
        if status != "ok":
            detail = answer or "follow-up needs a new document lookup"
            if "follow-up needs a new document lookup" not in detail.lower():
                detail = f"{detail}\n\nfollow-up needs a new document lookup"
            text, support = format_abstain_text(detail)
            return _done(
                text=text,
                status="insufficient_information",
                reason=support or "follow-up needs a new document lookup",
                status_reason="no_evidence",
            )
    except Exception as exc:
        return _done(
            text="insufficient information",
            status="insufficient_information",
            reason=f"followup error: {type(exc).__name__}",
            status_reason="provider_unavailable",
        )
