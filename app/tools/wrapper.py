from __future__ import annotations

import json
import logging
import time
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from app.config import DOC_STORE_DIR, MAX_TOOL_CALLS
from app.logging_setup import short

logger = logging.getLogger(__name__)

# Hard ceiling for judging: never above 6 even if config/env is mis-set.
HARD_MAX_TOOL_CALLS = 6


class BudgetExceededError(RuntimeError):
    """Raised when a question exceeds the max tool-call budget."""


class NoActiveSessionError(RuntimeError):
    """Raised when a document tool is called without a request-local session."""


@dataclass
class ToolCallRecord:
    question_id: str
    tool: str
    args: dict[str, Any]
    result_summary: str
    timestamp: float
    call_index: int
    error: str | None = None
    elapsed_ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "tool": self.tool,
            "args": self.args,
            "result_summary": self.result_summary,
            "timestamp": self.timestamp,
            "call_index": self.call_index,
            "error": self.error,
            "elapsed_ms": round(float(self.elapsed_ms or 0.0), 3),
        }


@dataclass
class ToolSession:
    question_id: str
    doc_id: str | None = None
    max_calls: int = MAX_TOOL_CALLS
    calls_used: int = 0
    trace: list[ToolCallRecord] = field(default_factory=list)
    _token: Token | None = field(default=None, repr=False, compare=False)

    @property
    def budget_left(self) -> int:
        return max(0, self.max_calls - self.calls_used)

    def require_doc(self, doc_id: str | None) -> None:
        if self.doc_id and doc_id and doc_id != self.doc_id:
            raise PermissionError(
                f"tool call for doc {doc_id!r} blocked; session bound to {self.doc_id!r}"
            )

    def call(self, tool_name: str, fn: Callable[..., Any], **kwargs: Any) -> Any:
        if "doc_id" in kwargs:
            self.require_doc(str(kwargs.get("doc_id") or ""))

        # Reserve the slot before executing so failures still consume budget.
        next_index = self.calls_used + 1
        if next_index > self.max_calls:
            record = ToolCallRecord(
                question_id=self.question_id,
                tool=tool_name,
                args=kwargs,
                result_summary="REFUSED: budget exceeded",
                timestamp=time.time(),
                call_index=next_index,
                error="budget_exceeded",
            )
            self.trace.append(record)
            _persist_record_safe(record)
            raise BudgetExceededError(
                f"tool call {next_index} refused; max is {self.max_calls}"
            )

        self.calls_used = next_index
        arg_preview = _args_preview(tool_name, kwargs)
        logger.info(
            "tool #%d/%d -> %s %s  qid=%s",
            next_index,
            self.max_calls,
            tool_name,
            arg_preview,
            self.question_id,
        )
        started = time.perf_counter()
        try:
            result = fn(**kwargs)
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000
            error = f"{type(exc).__name__}: {exc}"
            record = ToolCallRecord(
                question_id=self.question_id,
                tool=tool_name,
                args=kwargs,
                result_summary=f"ERROR: {error} budget_left={self.budget_left} elapsed_ms={elapsed_ms:.2f}",
                timestamp=time.time(),
                call_index=next_index,
                error=error,
                elapsed_ms=elapsed_ms,
            )
            self.trace.append(record)
            _persist_record_safe(record)
            logger.info(
                "tool #%d/%d FAIL %s -> %s  %.0fms  qid=%s",
                next_index,
                self.max_calls,
                tool_name,
                type(exc).__name__,
                elapsed_ms,
                self.question_id,
            )
            raise

        elapsed_ms = (time.perf_counter() - started) * 1000
        summary = (
            f"{_summarize(tool_name, result)} "
            f"budget_left={self.budget_left} elapsed_ms={elapsed_ms:.2f}"
        )
        record = ToolCallRecord(
            question_id=self.question_id,
            tool=tool_name,
            args=kwargs,
            result_summary=summary,
            timestamp=time.time(),
            call_index=next_index,
            error=None,
            elapsed_ms=elapsed_ms,
        )
        logger.info(
            "tool #%d/%d OK  %s -> %s  %.0fms  qid=%s",
            next_index,
            self.max_calls,
            tool_name,
            short(_summarize(tool_name, result), limit=100),
            elapsed_ms,
            self.question_id,
        )
        self.trace.append(record)
        _persist_record_safe(record)
        return result


_ACTIVE: ContextVar[ToolSession | None] = ContextVar("sixcall_tool_session", default=None)
_TRACES: dict[str, list[dict[str, Any]]] = {}
_TRACE_DIR = DOC_STORE_DIR.parent / "traces"
_TRACE_DIR.mkdir(parents=True, exist_ok=True)


def _clamp_max_calls(max_calls: int | None) -> int:
    base = MAX_TOOL_CALLS if max_calls is None else int(max_calls)
    if base < 1:
        raise ValueError(f"max_calls must be >= 1, got {base}")
    if base > HARD_MAX_TOOL_CALLS:
        raise ValueError(
            f"max_calls {base} exceeds hard ceiling {HARD_MAX_TOOL_CALLS}"
        )
    return base


def start_question(
    question_id: str,
    max_calls: int | None = None,
    *,
    doc_id: str | None = None,
) -> ToolSession:
    """Bind a request-local session (ContextVar). Replaces any prior token in this context."""
    session = ToolSession(
        question_id=question_id,
        doc_id=doc_id,
        max_calls=_clamp_max_calls(max_calls),
    )
    token = _ACTIVE.set(session)
    session._token = token
    _TRACES[question_id] = []
    try:
        _trace_path(question_id).write_text("[]", encoding="utf-8")
    except Exception as exc:
        logger.warning("trace_init_failed qid=%s err=%s", question_id, type(exc).__name__)
    return session


def get_active_session() -> ToolSession | None:
    return _ACTIVE.get()


def require_active_session() -> ToolSession:
    session = _ACTIVE.get()
    if session is None:
        raise NoActiveSessionError(
            "document tool requires an active question session"
        )
    return session


def clear_active_session() -> None:
    session = _ACTIVE.get()
    if session is not None and session._token is not None:
        try:
            _ACTIVE.reset(session._token)
            return
        except Exception:
            pass
    _ACTIVE.set(None)


def get_trace(question_id: str) -> list[dict[str, Any]]:
    if question_id in _TRACES and _TRACES[question_id]:
        return list(_TRACES[question_id])
    try:
        from app.db.repository import load_tool_trace

        db_rows = load_tool_trace(question_id)
        if db_rows:
            return db_rows
    except Exception:
        pass
    path = _trace_path(question_id)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except Exception:
            return []
    return []


def _trace_path(question_id: str) -> Path:
    safe = "".join(c for c in question_id if c.isalnum() or c in "-_")[:64]
    return _TRACE_DIR / f"{safe}.json"


def _persist_record_safe(record: ToolCallRecord) -> None:
    """Best-effort audit write. Never raises into the tool path (fail-open for I/O only)."""
    try:
        _save_record(record)
    except Exception as exc:
        logger.warning(
            "trace_persist_failed qid=%s call=%s err=%s",
            record.question_id,
            record.call_index,
            type(exc).__name__,
        )


def _save_record(record: ToolCallRecord) -> None:
    payload = record.as_dict()
    _TRACES.setdefault(record.question_id, []).append(payload)
    path = _trace_path(record.question_id)
    existing: list[dict[str, Any]] = []
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                existing = loaded
        except Exception:
            existing = []
    existing.append(payload)
    path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    # Local trace remains durable after each call. Remote rows are batched with
    # the completed answer so network latency cannot consume the evidence budget.


def _summarize(tool_name: str, result: Any) -> str:
    if tool_name == "get_page":
        text = str(result or "")
        return f"page_chars={len(text)} preview={text[:120]!r}"
    if tool_name == "search_keyword":
        pages = list(result or [])
        return f"pages={pages[:20]}{'…' if len(pages) > 20 else ''} count={len(pages)}"
    if tool_name in ("list_documents", "list_headings"):
        items = list(result or [])
        return f"count={len(items)}"
    return repr(result)[:200]


def _args_preview(tool_name: str, kwargs: dict[str, Any]) -> str:
    if tool_name == "get_page":
        return f"page={kwargs.get('page_number') or kwargs.get('page')}"
    if tool_name == "search_keyword":
        kw = kwargs.get("keyword")
        return f"keyword={short(kw if not isinstance(kw, list) else kw, limit=60)}"
    if tool_name in ("list_headings", "list_documents"):
        return f"doc={short(kwargs.get('doc_id'), limit=16)}"
    skip = {"doc_id"}
    parts = [f"{k}={short(v, limit=40)}" for k, v in kwargs.items() if k not in skip]
    return " ".join(parts[:4]) or "-"
