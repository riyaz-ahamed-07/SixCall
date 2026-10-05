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


def test_new_lookup_not_treated_as_followup():
    history = [
        {"role": "user", "text": "What is A*?"},
        {"role": "assistant", "text": "A* is a search algorithm."},
    ]
    assert not is_followup_question(
        "Define the configuration space on page 9", history
    )
