from __future__ import annotations

from app.agent.loop import run_agent
from app.store.document_store import (
    DocRecord,
    Heading,
    build_inverted_index,
    reset_store_for_tests,
)
from app.tools.wrapper import clear_active_session


def _seed(tmp_path, pages: dict[int, str], headings: list[Heading]):
    store = reset_store_for_tests(tmp_path / "docs")
    rec = DocRecord(
        doc_id="abcd1234abcd1234",
        meta={"page_count": max(pages), "title": "policy", "source_name": "policy.pdf"},
        pages=pages,
        labels={},
        headings=headings,
        index=build_inverted_index(pages),
    )
    store._docs[rec.doc_id] = rec
    return rec.doc_id


def test_supersede_forces_latest_keyword_hit_into_pages_used(tmp_path, monkeypatch):
    clear_active_session()
    pages = {
        i: f"Filler page {i} discusses nothing special." for i in range(1, 41)
    }
    pages[2] = "Refund policy. The refund window is 30 days."
    pages[3] = "More about the refund policy in this section."
    pages[6] = "Shipping policy only."
    pages[40] = (
        "Amendment. This supersedes the earlier refund policy. "
        "The refund window is 14 days."
    )
    doc_id = _seed(
        tmp_path,
        pages,
        [Heading(title="Refund policy", level=1, start=2, end=5)],
    )
    monkeypatch.setattr(
        "app.agent.loop.plan_question",
        lambda question, headings: {
            "rewritten": question,
            "qtype": "fact",
            "keywords": ["refund", "amendment"],
            "heading_hints": ["Refund policy"],
            "contradiction_sensitive": True,
            "intent": "fact",
            "format_card": "FORMAT=fact",
            "coding": False,
        },
    )

    def _draft(**kwargs):
        got = kwargs["pages"]
        assert 40 in got
        return {
            "status": "ok",
            "answer": "The refund window is 14 days.",
            "quotes": [{"text": "The refund window is 14 days.", "page": 40}],
        }

    monkeypatch.setattr("app.agent.loop.draft_answer", _draft)
    result = run_agent(doc_id, "What is the latest refund window after the amendment?")
    assert 40 in result["pages_used"]
    assert result["status"] == "ok"
    assert result["calls_used"] <= 6
    assert all(step.get("error") != "budget_exceeded" for step in result["tool_trace"])
    clear_active_session()


def test_repair_get_page_when_draft_abstains_and_budget_remains(tmp_path, monkeypatch):
    clear_active_session()
    pages = {i: f"Filler page {i}." for i in range(1, 10)}
    pages[1] = "Alpha section opens with background only."
    pages[2] = "Alpha section continues with background only."
    pages[9] = "Alpha result. The refund window is 14 days."
    doc_id = _seed(
        tmp_path,
        pages,
        [Heading(title="Alpha section", level=1, start=1, end=2)],
    )
    monkeypatch.setattr(
        "app.agent.loop.plan_question",
        lambda question, headings: {
            "rewritten": question,
            "qtype": "fact",
            "keywords": ["alpha"],
            "heading_hints": ["Alpha section"],
            "contradiction_sensitive": False,
            "intent": "fact",
            "format_card": "FORMAT=fact",
            "coding": False,
        },
    )
    calls = {"n": 0}

    def _draft(**kwargs):
        calls["n"] += 1
        got = kwargs["pages"]
        if calls["n"] == 1:
            assert 9 not in got
            return {
                "status": "insufficient_information",
                "answer": "The excerpts do not state the window.",
                "quotes": [],
            }
        assert 9 in got
        return {
            "status": "ok",
            "answer": "The refund window is 14 days.",
            "quotes": [{"text": "The refund window is 14 days.", "page": 9}],
        }

    monkeypatch.setattr("app.agent.loop.draft_answer", _draft)
    result = run_agent(doc_id, "Where is alpha?")
    assert result["status"] == "ok"
    assert 9 in result["pages_used"]
    assert calls["n"] == 2
    assert result["calls_used"] <= 6
    assert result["calls_used"] >= 1
    clear_active_session()


def test_ocr_is_off_by_default(tmp_path, monkeypatch):
    import pymupdf

    monkeypatch.delenv("SIXCALL_OCR", raising=False)

    def _boom(self, *args, **kwargs):
        raise AssertionError("OCR must stay off unless SIXCALL_OCR=1")

    monkeypatch.setattr(pymupdf.Page, "get_textpage_ocr", _boom)
    pdf = tmp_path / "sparse.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((72, 72), "x")
        doc.save(pdf)
    from app.store.document_store import DocumentStore

    store = DocumentStore(tmp_path / "store", use_db=False)
    doc_id = store.ingest_pdf(pdf, source_name="sparse.pdf")
    assert store.get(doc_id) is not None
