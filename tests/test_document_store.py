from __future__ import annotations

from pathlib import Path

import pymupdf as fitz
import pytest

from app.store.document_store import (
    InvalidPageNumberError,
    PageNotFoundError,
    UnknownDocumentError,
    reset_store_for_tests,
)


def _make_pdf(path: Path, pages: list[str]) -> None:
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()


def test_ingest_deterministic_and_idempotent(tmp_path: Path) -> None:
    store = reset_store_for_tests(tmp_path / "docs")
    pdf = tmp_path / "policy.pdf"
    _make_pdf(pdf, ["Refund window is 14 days."])

    a = store.ingest_pdf(pdf)
    b = store.ingest_pdf(pdf)
    assert a == b
    assert len(a) == 16
    assert store.get(a) is not None
    assert store.get_page(a, 1)


def test_get_page_rejects_invalid_and_missing(tmp_path: Path) -> None:
    store = reset_store_for_tests(tmp_path / "docs")
    pdf = tmp_path / "one.pdf"
    _make_pdf(pdf, ["Only page one."])
    doc_id = store.ingest_pdf(pdf)

    with pytest.raises(InvalidPageNumberError):
        store.get_page(doc_id, 0)
    with pytest.raises(InvalidPageNumberError):
        store.get_page(doc_id, -1)
    with pytest.raises(PageNotFoundError):
        store.get_page(doc_id, 99)
    with pytest.raises(UnknownDocumentError):
        store.get_page("", 1)
    with pytest.raises(UnknownDocumentError):
        store.get_page("missing-doc", 1)


def test_search_keyword_empty_and_sorted(tmp_path: Path) -> None:
    store = reset_store_for_tests(tmp_path / "docs")
    pdf = tmp_path / "multi.pdf"
    _make_pdf(
        pdf,
        [
            "Alpha refund window.",
            "Beta shipping only.",
            "Amended refund window.",
        ],
    )
    doc_id = store.ingest_pdf(pdf)

    assert store.search_keyword(doc_id, "") == []
    assert store.search_keyword(doc_id, "   ") == []
    pages = store.search_keyword(doc_id, "refund")
    assert pages == [1, 3]
    assert pages == sorted(pages)


def test_list_documents_stable_sort(tmp_path: Path) -> None:
    store = reset_store_for_tests(tmp_path / "docs")
    pdf_b = tmp_path / "bravo.pdf"
    pdf_a = tmp_path / "alpha.pdf"
    _make_pdf(pdf_b, ["Bravo content"])
    _make_pdf(pdf_a, ["Alpha content"])
    store.ingest_pdf(pdf_b)
    store.ingest_pdf(pdf_a)

    titles = [d["title"] for d in store.list_documents()]
    assert titles == sorted(titles)


def test_corrupt_json_skipped(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "bad.json").write_text("{not-json", encoding="utf-8")
    store = reset_store_for_tests(docs)
    assert store.list_documents() == []
