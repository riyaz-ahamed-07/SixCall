from __future__ import annotations

import os
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agent.followup import (
    is_followup_question,
    prior_answer_was_insufficient,
    run_followup,
)
from app.agent.loop import run_agent
from app.agent.overview import is_overview_question, run_light_summary, run_overview
from app.store.document_store import get_store
from app.tools.wrapper import get_trace as _get_trace


class Answer(BaseModel):
    text: str
    status: Literal["ok", "insufficient_information"]
    pages_used: list[int] = Field(default_factory=list)
    tool_trace: list[dict[str, Any]] = Field(default_factory=list)
    calls_used: int = 0
    question_id: str = ""
    reason: str | None = None
    status_reason: str | None = None
    quotes: list[dict[str, Any]] = Field(default_factory=list)
    intent: str | None = None
    strategy: str | None = None


def ingest_pdf(path: str, *, owner_id: str | None = None, source_name: str | None = None) -> str:
    """Parse and store a PDF. Returns stable doc_id (sha256[:16])."""
    return get_store().ingest_pdf(path, owner_id=owner_id, source_name=source_name)


def _to_answer(result: dict[str, Any]) -> Answer:
    return Answer(
        text=result.get("text") or "",
        status=result.get("status") or "insufficient_information",
        pages_used=list(result.get("pages_used") or []),
        tool_trace=list(result.get("tool_trace") or []),
        calls_used=int(result.get("calls_used") or 0),
        question_id=str(result.get("question_id") or ""),
        reason=result.get("reason"),
        status_reason=result.get("status_reason"),
        quotes=list(result.get("quotes") or []),
        intent=result.get("intent"),
        strategy=result.get("strategy"),
    )


def _persist_answer(
    doc_id: str,
    question: str,
    answer: Answer,
    *,
    owner_id: str | None = None,
) -> None:
    try:
        from app.db.repository import save_answer, save_tool_calls

        save_answer(
            question_id=answer.question_id,
            doc_id=doc_id,
            question=question,
            answer=answer.model_dump(),
            owner_id=owner_id,
        )
        save_tool_calls(answer.tool_trace, owner_id=owner_id)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("answer_db_persist_failed qid=%s error=%s", answer.question_id, type(exc).__name__)


def _followups_enabled() -> bool:
    """Zero-tool follow-ups are off unless SIXCALL_FOLLOWUPS=1."""
    return os.getenv("SIXCALL_FOLLOWUPS", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def ask(
    doc_id: str,
    question: str,
    *,
    history: list[dict[str, Any]] | None = None,
    owner_id: str | None = None,
) -> Answer:
    """
    Route:
      SIXCALL_FOLLOWUPS=1 and a pure clarification → prior quotes, else tools
      overview phrasing → real get_page overview (never the light TOC summary)
      else → budgeted tree+keyword agent
    """
    hist = list(history or [])
    # Live /ask does not answer from memory unless the flag is explicitly on,
    # and it never returns a result that used zero tools.
    routed_via_agent = False
    if (
        _followups_enabled()
        and is_followup_question(question, hist)
        and not prior_answer_was_insufficient(hist)
    ):
        result = run_followup(doc_id, question, hist)
        if result.get("status") != "ok" or int(result.get("calls_used") or 0) <= 0:
            result = run_agent(doc_id, question)
            routed_via_agent = True
    elif is_overview_question(question):
        result = run_overview(doc_id, question)
    else:
        result = run_agent(doc_id, question)
        routed_via_agent = True
    if not routed_via_agent and int(result.get("calls_used") or 0) <= 0:
        result = run_agent(doc_id, question)
    answer = _to_answer(result)
    _persist_answer(doc_id, question, answer, owner_id=owner_id)
    return answer


def overview(
    doc_id: str,
    question: str | None = None,
    *,
    owner_id: str | None = None,
    light: bool = False,
) -> Answer:
    """Explicit overview. light=True → headings-only (1 tool call) for post-ingest."""
    q = (question or "What is this document about?").strip()
    result = run_light_summary(doc_id) if light else run_overview(doc_id, q)
    answer = _to_answer(result)
    _persist_answer(doc_id, q if not light else "Document orientation (TOC)", answer, owner_id=owner_id)
    return answer


def list_docs(*, owner_id: str | None = None) -> list[dict[str, Any]]:
    return get_store().list_documents(owner_id=owner_id)


def get_trace(question_id: str, *, owner_id: str | None = None) -> list[dict[str, Any]]:
    rows = _get_trace(question_id)
    if not owner_id or owner_id == "local":
        return rows
    try:
        from app.db.connection import connect, db_enabled

        if not db_enabled():
            return rows
        with connect() as conn:
            row = conn.execute(
                "SELECT owner_id FROM questions WHERE question_id = %s",
                (question_id,),
            ).fetchone()
        if row is None:
            return rows
        if str(row["owner_id"] or "") != str(owner_id):
            return []
        if rows:
            return rows
        from app.db.repository import load_tool_trace

        return load_tool_trace(question_id, owner_id=owner_id)
    except Exception:
        return rows
