from contextlib import contextmanager
from unittest.mock import MagicMock

import pymupdf

from app.store.document_store import DocumentStore, build_inverted_index, stem_token
from app.agent import planner
from app.db import repository
from app.tools import wrapper


def test_uploaded_metadata_is_persisted_once(tmp_path, monkeypatch):
    pdf = tmp_path / "temporary.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((72, 72), "Path planning finds a route while avoiding obstacles.")
        doc.save(pdf)
    store = DocumentStore(tmp_path / "store", use_db=False)
    persist = MagicMock(wraps=store._persist)
    monkeypatch.setattr(store, "_persist", persist)
    doc_id = store.ingest_pdf(pdf, owner_id="owner", source_name="Robotics.pdf")
    assert persist.call_count == 1
    assert store.get(doc_id).meta["source_name"] == "Robotics.pdf"
    assert "source_path" not in store.get(doc_id).meta
    store.ingest_pdf(pdf, owner_id="owner", source_name="Robotics.pdf")
    assert persist.call_count == 1


def test_repeated_tokens_preserve_page_index():
    stem_token.cache_clear()
    index = build_inverted_index({1: "robots robots robots", 2: "robot robot"})
    assert index[stem_token("robots")] == [1, 2]
    assert stem_token.cache_info().hits > 0


def test_exact_topic_skips_provider(monkeypatch):
    def forbidden():
        raise AssertionError("Exact-heading question should not call provider")
    monkeypatch.setattr(planner, "get_llm", forbidden)
    plan = planner.plan_question("What is path planning?", [
        {"title": "2.1 Path planning", "level": 2, "start": 9, "end": 11}
    ])
    assert plan["keywords"] == ["Path planning"]
    assert plan["heading_hints"] == ["Path planning"]


def test_trace_batch_uses_one_connection(monkeypatch):
    conn = MagicMock()
    connections = []
    @contextmanager
    def connect():
        connections.append(conn)
        yield conn
    monkeypatch.setattr(repository, "db_enabled", lambda: True)
    monkeypatch.setattr(repository, "connect", connect)
    records = [{"question_id": "q", "call_index": i, "tool": "get_page",
                "args": {"page_number": i}, "timestamp": 1} for i in range(1, 7)]
    repository.save_tool_calls(records)
    assert len(connections) == 1
    rows = conn.cursor.return_value.__enter__.return_value.executemany.call_args.args[1]
    assert len(rows) == 6
    conn.commit.assert_called_once()


def test_tool_trace_does_not_wait_for_remote_db(tmp_path, monkeypatch):
    monkeypatch.setattr(wrapper, "_TRACE_DIR", tmp_path)
    monkeypatch.setattr(repository, "ensure_question", MagicMock(side_effect=AssertionError("remote I/O")))
    monkeypatch.setattr(repository, "save_tool_call", MagicMock(side_effect=AssertionError("remote I/O")))
    session = wrapper.start_question("latency-test")
    try:
        assert session.call("get_page", lambda: "source text") == "source text"
        assert len(wrapper.get_trace("latency-test")) == 1
        assert (tmp_path / "latency-test.json").exists()
        repository.ensure_question.assert_not_called()
        repository.save_tool_call.assert_not_called()
    finally:
        wrapper.clear_active_session()
