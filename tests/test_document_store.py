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


def test_ingest_bytes_owner_duplicate_skips_reparse(tmp_path: Path, monkeypatch) -> None:
    store = reset_store_for_tests(tmp_path / "docs")
    pdf = tmp_path / "cs.pdf"
    _make_pdf(pdf, ["Computer Science is about problem solving."])
    raw = pdf.read_bytes()
    first = store.ingest_bytes(raw, owner_id="user-a", source_name="cs.pdf")

    calls = {"n": 0}
    import app.store.document_store as ds

    real_open = ds.fitz.open

    def counting_open(*args, **kwargs):
        calls["n"] += 1
        return real_open(*args, **kwargs)

    monkeypatch.setattr(ds.fitz, "open", counting_open)
    second = store.ingest_bytes(raw, owner_id="user-a", source_name="cs.pdf")
    assert second == first
    assert calls["n"] == 0


def test_ingest_bytes_different_owners_stay_isolated(tmp_path: Path) -> None:
    store = reset_store_for_tests(tmp_path / "docs")
    pdf = tmp_path / "cs.pdf"
    _make_pdf(pdf, ["Computer Science is about problem solving."])
    raw = pdf.read_bytes()
    a = store.ingest_bytes(raw, owner_id="user-a", source_name="cs.pdf")
    b = store.ingest_bytes(raw, owner_id="user-b", source_name="cs.pdf")
    assert a != b


def test_ingest_pymupdf4llm_keeps_searchable_text_and_table_digits(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SIXCALL_MARKDOWN_EXTRACT", "1")
    store = reset_store_for_tests(tmp_path / "docs")
    pdf = tmp_path / "table.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Refund policy", fontsize=18)
    page.insert_text((72, 110), "The refund window is 14 days.")
    data = [["Item", "Days", "Fee"], ["Widget", "14", "3"]]
    y = 160
    for row in data:
        x = 72
        for cell in row:
            rect = fitz.Rect(x, y, x + 80, y + 22)
            page.draw_rect(rect)
            page.insert_textbox(rect, cell, fontsize=10, align=1)
            x += 80
        y += 22
    doc.save(pdf)
    doc.close()

    doc_id = store.ingest_pdf(pdf)
    text = store.get_page(doc_id, 1)
    assert "refund window" in text.lower()
    assert "14" in text
    assert "|" in text
    assert store.search_keyword(doc_id, "14") == [1]
    assert 1 in store.search_keyword(doc_id, "refund")


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


def test_ingest_writes_local_cache_before_db_and_does_not_block(tmp_path: Path, monkeypatch) -> None:
    """Upload returns after local JSON; remote DB sync runs in the background."""
    import json
    import threading
    import time

    from app.store.document_store import DocumentStore

    monkeypatch.setattr("app.db.connection.db_enabled", lambda: True)
    monkeypatch.setattr("app.db.repository.load_all_documents", lambda **kw: [])

    started = threading.Event()
    finished = threading.Event()

    def slow_save(rec) -> None:
        started.set()
        time.sleep(0.5)
        finished.set()

    monkeypatch.setattr("app.db.repository.save_document", slow_save)

    store = DocumentStore(tmp_path / "docs", use_db=True, disk_cache="staging")
    pdf = tmp_path / "policy.pdf"
    _make_pdf(pdf, ["Refund window is 14 days."])
    raw = pdf.read_bytes()

    doc_id = store.ingest_bytes(raw, owner_id="user-a", source_name="policy.pdf")

    # Must not wait for the 0.5s DB write — staged disk + memory are enough.
    assert not finished.is_set(), "ingest blocked until DB save finished"
    cache = tmp_path / "docs" / f"{doc_id}.json"
    assert cache.is_file()
    payload = json.loads(cache.read_text(encoding="utf-8"))
    assert "pages" in payload and payload["pages"]
    assert store.get(doc_id) is not None
    assert store.get_page(doc_id, 1)

    assert started.wait(2.0), "background DB sync never started"
    assert finished.wait(2.0), "background DB sync never finished"
    # Purge runs right after save returns — wait briefly for unlink.
    for _ in range(50):
        if not cache.exists():
            break
        time.sleep(0.02)
    assert not cache.exists()
    assert store.get_page(doc_id, 1)


def test_ingest_without_disk_waits_for_supabase(tmp_path: Path, monkeypatch) -> None:
    """Render mode: no .data/docs — durable write must finish before HTTP returns."""
    import threading
    import time

    from app.store.document_store import DocumentStore

    monkeypatch.setattr("app.db.connection.db_enabled", lambda: True)
    monkeypatch.setattr("app.db.repository.load_all_documents", lambda **kw: [])

    finished = threading.Event()

    def slow_save(rec) -> None:
        time.sleep(0.2)
        finished.set()

    monkeypatch.setattr("app.db.repository.save_document", slow_save)

    store = DocumentStore(tmp_path / "docs", use_db=True, disk_cache=False)
    pdf = tmp_path / "policy.pdf"
    _make_pdf(pdf, ["Refund window is 14 days."])
    doc_id = store.ingest_bytes(
        pdf.read_bytes(), owner_id="user-a", source_name="policy.pdf"
    )

    assert finished.is_set(), "ingest returned before Supabase save finished"
    assert not (tmp_path / "docs" / f"{doc_id}.json").exists()
    assert store.get_page(doc_id, 1)


def test_store_startup_does_not_block_on_remote_hydrate(tmp_path: Path, monkeypatch) -> None:
    """Local catalogs load sync; Supabase hydrate must not hold DocumentStore().__init__."""
    import threading
    import time

    from app.store.document_store import DocumentStore

    monkeypatch.setattr("app.db.connection.db_enabled", lambda: True)

    started = threading.Event()
    release = threading.Event()

    def slow_load(**kw):
        started.set()
        release.wait(2.0)
        return []

    monkeypatch.setattr("app.db.repository.load_all_documents", slow_load)

    t0 = time.perf_counter()
    store = DocumentStore(tmp_path / "docs", use_db=True)
    assert (time.perf_counter() - t0) < 0.5
    assert started.wait(1.0), "background hydrate never started"
    release.set()
    assert isinstance(store._docs, dict)


def test_ingest_reuses_disk_cache_without_reparse(tmp_path: Path, monkeypatch) -> None:
    """Same owner+bytes after memory wipe reloads local JSON — no pymupdf reopen."""
    from app.store.document_store import DocumentStore
    from app.store import document_store as ds_mod

    store = DocumentStore(tmp_path / "docs", use_db=False, disk_cache="keep")
    ds_mod._STORE = store
    pdf = tmp_path / "cs.pdf"
    _make_pdf(pdf, ["Computer Science is about problem solving."])
    raw = pdf.read_bytes()
    first = store.ingest_bytes(raw, owner_id="user-a", source_name="cs.pdf")
    assert (tmp_path / "docs" / f"{first}.json").is_file()

    store._docs.clear()

    calls = {"n": 0}
    import app.store.document_store as ds

    real_open = ds.fitz.open

    def counting_open(*args, **kwargs):
        calls["n"] += 1
        return real_open(*args, **kwargs)

    monkeypatch.setattr(ds.fitz, "open", counting_open)
    second = store.ingest_bytes(raw, owner_id="user-a", source_name="cs.pdf")
    assert second == first
    assert calls["n"] == 0
    assert store.get(first) is not None
