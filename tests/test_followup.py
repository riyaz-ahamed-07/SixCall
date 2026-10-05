from __future__ import annotations

from app.agent.followup import is_followup_question


def test_followup_detection_with_history():
    history = [
        {"role": "user", "text": "What is the refund window?"},
        {
            "role": "assistant",
            "text": "The refund window is 14 days.",
            "quotes": [{"page": 1, "text": "refund window is 14 days"}],
        },
    ]
    assert is_followup_question("Explain that more simply", history)
    assert is_followup_question("Which page states that?", history)
    assert is_followup_question("why?", history)


def test_followup_skips_without_history():
    assert not is_followup_question("Explain that more simply", [])
    assert not is_followup_question("Explain that more simply", None)


def test_normal_questions_are_not_zero_tool_followups():
    history = [
        {"role": "user", "text": "What is the refund window?"},
        {
            "role": "assistant",
            "text": "The refund window is 14 days.",
            "status": "ok",
            "quotes": [{"page": 1, "text": "refund window is 14 days"}],
        },
    ]
    assert not is_followup_question("What is the refund window?", history)
    assert not is_followup_question("Explain the amendment", history)
    assert not is_followup_question(
        "What is the latest policy that supersedes the old one?", history
    )
    assert not is_followup_question("why is the refund only 14 days?", history)


def test_ungrounded_followup_is_not_accepted(monkeypatch):
    from app.agent.followup import run_followup

    class _Fake:
        def complete_json(self, *args, **kwargs):
            return {
                "status": "ok",
                "answer": "Customers may teleport instantly.",
                "quotes": [{"page": 1, "text": "Customers may teleport instantly."}],
            }

    monkeypatch.setattr("app.agent.followup.get_llm", lambda: _Fake())
    history = [
        {"role": "user", "text": "What is the refund window?"},
        {
            "role": "assistant",
            "text": "The refund window is 14 days.",
            "status": "ok",
            "quotes": [{"page": 1, "text": "The refund window is 14 days."}],
        },
    ]
    result = run_followup("doc", "why?", history)
    assert result["status"] == "insufficient_information"
    assert result["calls_used"] == 0


def test_ask_normal_question_uses_tools(monkeypatch):
    from app.api import ask

    def _followup(*args, **kwargs):
        raise AssertionError("normal question must not take the zero-tool path")

    def _agent(doc_id, question):
        return {
            "text": "The refund window is 14 days.",
            "status": "ok",
            "pages_used": [4],
            "tool_trace": [{"tool": "get_page", "call_index": 2}],
            "calls_used": 3,
            "question_id": "q-tools",
            "quotes": [{"page": 4, "text": "The refund window is 14 days."}],
        }

    monkeypatch.setattr("app.api.run_followup", _followup)
    monkeypatch.setattr("app.api.run_agent", _agent)
    monkeypatch.setattr("app.api._persist_answer", lambda *a, **k: None)
    history = [
        {"role": "user", "text": "Hello"},
        {
            "role": "assistant",
            "text": "The refund window is 30 days.",
            "status": "ok",
            "quotes": [{"page": 1, "text": "The refund window is 30 days."}],
        },
    ]
    answer = ask(
        "doc",
        "Explain the amendment that supersedes the old rule",
        history=history,
    )
    assert answer.calls_used > 0
    assert answer.tool_trace
    assert answer.pages_used == [4]


def test_new_lookup_not_treated_as_followup():
    history = [
        {"role": "user", "text": "What is A*?"},
        {"role": "assistant", "text": "A* is a search algorithm."},
    ]
    assert not is_followup_question(
        "Define the configuration space on page 9", history
    )
