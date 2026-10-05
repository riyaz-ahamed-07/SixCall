from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pymupdf as fitz

from app.api import ask, ingest_pdf
from app.store.document_store import reset_store_for_tests
from app.tools.wrapper import clear_active_session


def _make_pdf(path: Path, text: str = "Alpha bravo charlie.") -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    doc.save(path)
    doc.close()


def test_ingest_is_deterministic_for_same_bytes(tmp_path: Path):
    clear_active_session()
    reset_store_for_tests(tmp_path / "docs")
    pdf = tmp_path / "same.pdf"
    _make_pdf(pdf)
    a = ingest_pdf(str(pdf))
    b = ingest_pdf(str(pdf))
    assert a == b
    assert len(a) == 16


def test_empty_search_returns_insufficient_information(tmp_path: Path):
    clear_active_session()
    reset_store_for_tests(tmp_path / "docs")
    pdf = tmp_path / "tiny.pdf"
    _make_pdf(pdf, "Only zebra appears here.")
    doc_id = ingest_pdf(str(pdf))

    with patch("app.agent.loop.pick_toc") as plan:
        plan.return_value = {
            "sections": [],
            "use_terms": ["xylophone-not-present"],
        }
        answer = ask(doc_id, "Where is xylophone?")

    assert answer.status == "insufficient_information"
    assert "insufficient" in answer.text.lower()
    assert answer.calls_used <= 6
