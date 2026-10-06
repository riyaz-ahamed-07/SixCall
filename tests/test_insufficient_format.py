from __future__ import annotations

from app.agent.loop import _format_insufficient


def test_insufficient_label_not_duplicated():
    text, support = _format_insufficient(
        "insufficient information\n\n"
        "The excerpts mention ASCII but not the value for '0'."
    )
    assert text.startswith("insufficient information\n\n")
    assert text.count("insufficient information") == 1
    assert support and "ASCII" in support


def test_plain_reason():
    text, support = _format_insufficient("no pages fetched")
    assert text == "insufficient information\n\nno pages fetched"
    assert support == "no pages fetched"
