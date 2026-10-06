import pytest

from app.agent.evidence import repair_quotes
from app.agent.loop import _accept_draft
from app.agent.navigate import select_initial_pages
from app.index.dual_index import build_precision_index
from app.store.document_store import (
    DocRecord, build_inverted_index, reset_store_for_tests,
)


@pytest.mark.parametrize("keyword", ["Voltix", "voltix", "VOLTIX"])
def test_capitalization_does_not_hide_lowercase_pages(tmp_path, keyword):
    pages = {1: "Voltix is introduced.", 2: "voltix provides detailed specifications."}
    store = reset_store_for_tests(tmp_path / "docs")
    record = DocRecord(
        doc_id="case-regression", meta={"page_count": 2}, pages=pages,
        labels={}, headings=[], index=build_inverted_index(pages),
        precision_index=build_precision_index(pages),
    )
    store._docs[record.doc_id] = record
    assert store.search_keyword(record.doc_id, keyword) == [1, 2]


def test_contradictory_quote_cannot_be_repaired_or_accepted():
    pages = {1: "Employees are not eligible for reimbursement under this policy."}
    invented = "Employees are eligible for reimbursement under this policy."
    quotes = [{"text": invented, "page": 1}]
    assert repair_quotes(quotes, pages) == []
    accepted, _, reason = _accept_draft(
        {"status": "ok", "answer": invented, "quotes": quotes}, pages,
    )
    assert accepted is None
    assert reason == "quote_mismatch"


def test_quote_batch_with_one_invalid_quote_is_rejected_entirely():
    source = "Employees are not eligible for reimbursement under this policy."
    quotes = [
        {"text": source, "page": 1},
        {"text": source.replace("not ", ""), "page": 1},
    ]
    assert repair_quotes(quotes, {1: source}) == []


def test_overview_abstains_instead_of_repairing_contradictory_quote(monkeypatch):
    from app.agent.overview import run_overview

    source = "Employees are not eligible for reimbursement under this policy."
    invented = source.replace("not ", "")
    monkeypatch.setattr("app.agent.overview.list_headings", lambda _: [
        {"title": "Policy", "start": 1, "end": 1},
    ])
    monkeypatch.setattr("app.agent.overview.get_page", lambda *_: source)
    calls = []

    def draft(**kwargs):
        calls.append(1)
        return {"status": "ok", "answer": invented,
                "quotes": [{"text": invented, "page": 1}]}

    monkeypatch.setattr("app.agent.overview.draft_answer", draft)
    result = run_overview("review-overview")
    assert result["status"] == "insufficient_information"
    assert result["status_reason"] == "invalid_output"
    assert calls == [1]


@pytest.mark.parametrize("wide,slots", [(False, 3), (True, 4)])
def test_available_reads_are_used_before_generation(wide, slots):
    assert select_initial_pages([1, 2, 3, 4, 5], slots, wide=wide) == list(range(1, slots + 1))
    assert select_initial_pages([1], 0, wide=wide) == []
