from __future__ import annotations

import re
import uuid
from typing import Any

from app.deadline import clear_deadline, start_deadline
from app.config import REQUEST_DEADLINE_SEC
from app.llm.client import get_llm

_FOLLOWUP_CUE = re.compile(
    r"\b("
    r"that|this|it|those|these|they|them|above|previous|earlier|same|"
    r"more|again|clarify|elaborate|expand|explain|meaning|mean|"
    r"why|how\s+so|what\s+about|and\s+also|continue|go\s+on|"
    r"in\s+other\s+words|simpler|shorter|longer|which\s+page|"
    r"can\s+you|could\s+you|please\s+(explain|clarify|repeat)"
    r")\b",
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

JSON only:
{"status":"ok|insufficient_information","answer":"..."}
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
    """True when the user is continuing the prior answer, not starting a fresh lookup."""
    if not history:
        return False
    if prior_answer_was_insufficient(history):
        return False

    q = (question or "").strip()
    if not q:
        return False

    # Explicit new document lookups stay on the tool path
    if _NEW_TOPIC.search(q) and not _FOLLOWUP_CUE.search(q):
        return False

    words = q.split()
    if len(words) <= 16 and _FOLLOWUP_CUE.search(q):
        return True
    # Short questions without anaphoric cues are new lookups (e.g. "how to handle cost").
    return False


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
            "quotes": [],
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
        data = get_llm().complete_json(
            messages, temperature=0.1, light=False, max_attempts=1
        )
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
        if status != "ok":
            if not answer:
                answer = "insufficient information"
            return _done(
                text=answer,
                status="insufficient_information",
                reason="follow-up needs a new document lookup",
                status_reason="no_evidence",
            )
        return _done(text=answer, status="ok")
    except Exception as exc:
        return _done(
            text="insufficient information",
            status="insufficient_information",
            reason=f"followup error: {type(exc).__name__}",
            status_reason="provider_unavailable",
        )
