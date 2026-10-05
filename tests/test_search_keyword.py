from __future__ import annotations

from pathlib import Path

import pymupdf as fitz

from app.store.document_store import reset_store_for_tests
from app.tools.search_keyword import search_keyword
from app.tools.wrapper import clear_active_session, start_question


def _make_pdf(path: Path) -> None:
    doc = fitz.open()
    page1 = doc.new_page()
    page1.insert_text((72, 72), "Alpha policy refund window is 14 days.")
    page2 = doc.new_page()
    page2.insert_text((72, 72), "Beta section mentions shipping only.")
    page3 = doc.new_page()
    page3.insert_text((72, 72), "Amended refund window is 30 days.")
    doc.save(path)
    doc.close()


def test_search_keyword_returns_only_ints(tmp_path: Path):
    clear_active_session()
    store = reset_store_for_tests(tmp_path / "docs")
    pdf = tmp_path / "sample.pdf"
    _make_pdf(pdf)
    doc_id = store.ingest_pdf(pdf)

    start_question("q-search-ints", doc_id=doc_id, max_calls=6)
    try:
        pages = search_keyword(doc_id, "refund")
        assert isinstance(pages, list)
        assert all(isinstance(p, int) for p in pages)
        assert pages == [1, 3]

        phrase_pages = search_keyword(doc_id, "refund window")
        assert all(isinstance(p, int) for p in phrase_pages)
        assert 1 in phrase_pages and 3 in phrase_pages
    finally:
        clear_active_session()


def test_search_astar_ascii_and_normalize(tmp_path: Path):
    clear_active_session()
    store = reset_store_for_tests(tmp_path / "docs")
    pdf = tmp_path / "astar.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Optimality of A* search is proven when h is admissible.")
    doc.save(pdf)
    doc.close()
    doc_id = store.ingest_pdf(pdf)

    start_question("q-search-astar", doc_id=doc_id, max_calls=6)
    try:
        pages = search_keyword(doc_id, "A*")
        assert pages == [1]
        assert all(isinstance(p, int) for p in pages)

        # Query with PDF-style asterisk operator still resolves
        assert search_keyword(doc_id, "A\u2217") == [1]
    finally:
        clear_active_session()

    from app.store.document_store import tokenize
    from app.textutil import normalize_text

    assert normalize_text("A\u2217search") == "A*search"
    assert "a*" in tokenize("A\u2217search")
