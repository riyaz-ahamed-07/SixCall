from __future__ import annotations

from app.agent.verifier import verify_quotes
from app.agent.answerer import draft_answer


def test_quote_verifier_accepts_code_contiguous_span():
    pages = {
        1: 'int main(void) {\n  printf("hello");\n  return 0;\n}\n'
    }
    ok, failures = verify_quotes(
        [{"text": 'printf("hello");', "page": 1}],
        pages,
    )
    assert ok is True
    assert failures == []


def test_quote_verifier_accepts_exact_span():
    pages = {1: "The refund window is fourteen days for unused items."}
    ok, failures = verify_quotes(
        [{"text": "refund window is fourteen days", "page": 1}],
        pages,
    )
    assert ok is True
    assert failures == []


def test_quote_verifier_rejects_fabricated_quotes():
    pages = {1: "The refund window is fourteen days for unused items."}
    ok, failures = verify_quotes(
        [{"text": "Customers may teleport instantly", "page": 1}],
        pages,
    )
    assert ok is False
    assert failures


def test_quote_verifier_rejects_altered_number():
    pages = {1: "The refund window is 14 days for unused items."}
    ok, failures = verify_quotes(
        [{"text": "The refund window is 90 days for unused items.", "page": 1}],
        pages,
    )
    assert ok is False
    assert failures


def test_quote_verifier_rejects_removed_negation():
    pages = {1: "Employees are not eligible for refunds."}
    ok, failures = verify_quotes(
        [{"text": "Employees are eligible for refunds.", "page": 1}],
        pages,
    )
    assert ok is False
    assert failures


def test_quote_verifier_rejects_one_character_quote():
    pages = {1: "The refund window is 14 days."}
    ok, failures = verify_quotes(
        [{"text": "a", "page": 1}],
        pages,
    )
    assert ok is False
    assert failures


def test_quote_verifier_rejects_substring_inside_longer_word():
    pages = {1: "Workers are ineligible for early refunds under this policy."}
    ok, failures = verify_quotes(
        [{"text": "eligible", "page": 1}],
        pages,
    )
    assert ok is False
    assert failures


def test_near_span_accepts_typo_and_rejects_number_or_negation_swap():
    from app.agent.verifier import near_span

    span = "The refund window is 14 days for unused items."
    assert near_span("The refund window is 14 days for unused items.", span)
    assert near_span("The refund windwo is 14 days for unused items.", span)
    assert not near_span("The refund window is 90 days for unused items.", span)
    assert not near_span("Employees are eligible for refunds.", "Employees are not eligible for refunds.")
    assert not near_span("All items except food.", "All items including food.")


def test_unknown_evidence_id_is_rejected_even_when_text_is_on_page():
    pages = {1: "The refund window is 14 days for unused items."}
    ok, failures = verify_quotes(
        [{"id": "E99", "text": "The refund window is 14 days for unused items.", "page": 1}],
        pages,
        allowed_ids={"E1"},
        span_texts={"E1": "The refund window is 14 days for unused items."},
        spans=[{"id": "E1", "page": 1, "text": "The refund window is 14 days for unused items."}],
    )
    assert ok is False
    assert any("unknown evidence id" in f for f in failures)


def test_draft_rejects_empty_ok_answer(monkeypatch):
    from app.agent import answerer as answerer_mod

    class _FakeLLM:
        def complete_json(self, *args, **kwargs):
            return {
                "status": "ok",
                "answer": "   ",
                "quotes": [{"page": 1, "text": "refund window is fourteen days"}],
            }

    monkeypatch.setattr(answerer_mod, "get_llm", lambda: _FakeLLM())
    draft = draft_answer(
        question="What is the refund window?",
        plan={"intent": "fact", "format_card": "", "rewritten": "", "qtype": "fact"},
        pages={1: "The refund window is fourteen days."},
        unused_candidates=[],
        budget_left=0,
    )
    assert draft["status"] == "insufficient_information"
    assert draft.get("error") == "empty_answer"
