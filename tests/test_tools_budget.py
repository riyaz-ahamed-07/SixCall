from __future__ import annotations

import threading

import pytest

from app.tools.get_page import get_page
from app.tools.wrapper import (
    BudgetExceededError,
    NoActiveSessionError,
    clear_active_session,
    get_active_session,
    start_question,
)


def test_seventh_tool_call_is_blocked():
    clear_active_session()
    session = start_question("q-budget", max_calls=6)

    def _ok(**kwargs):
        return "ok"

    for i in range(6):
        assert session.call("list_documents", _ok) == "ok"
        assert session.calls_used == i + 1

    with pytest.raises(BudgetExceededError):
        session.call("list_documents", _ok)

    assert session.calls_used == 6
    assert session.trace[-1].error == "budget_exceeded"
    assert "REFUSED" in session.trace[-1].result_summary
    clear_active_session()


def test_max_calls_above_six_rejected():
    clear_active_session()
    with pytest.raises(ValueError):
        start_question("q-over", max_calls=7)


def test_tools_fail_closed_without_session():
    clear_active_session()
    with pytest.raises(NoActiveSessionError):
        get_page("any-doc", 1)


def test_context_sessions_do_not_cross_charge():
    """Each thread must keep its own ContextVar session (no global overwrite)."""
    clear_active_session()
    results: dict[str, object] = {}
    barrier = threading.Barrier(2)

    def worker(qid: str, doc: str) -> None:
        session = start_question(qid, doc_id=doc, max_calls=6)

        def _touch(**kwargs):
            return f"ok:{kwargs.get('doc_id')}"

        barrier.wait()
        out = session.call("get_page", _touch, doc_id=doc, page_number=1)
        results[qid] = {
            "out": out,
            "calls": session.calls_used,
            "trace_docs": [r.args.get("doc_id") for r in session.trace],
            "active_doc": get_active_session().doc_id if get_active_session() else None,
        }
        clear_active_session()

    t1 = threading.Thread(target=worker, args=("qa", "doc-a"))
    t2 = threading.Thread(target=worker, args=("qb", "doc-b"))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert results["qa"]["calls"] == 1
    assert results["qb"]["calls"] == 1
    assert results["qa"]["trace_docs"] == ["doc-a"]
    assert results["qb"]["trace_docs"] == ["doc-b"]
    assert results["qa"]["out"] == "ok:doc-a"
    assert results["qb"]["out"] == "ok:doc-b"
