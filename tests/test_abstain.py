from __future__ import annotations

from app.agent.abstain import format_abstain_text, strip_abstain_label


def test_format_abstain_strips_duplicate_label():
    text, support = format_abstain_text(
        "insufficient information\n\n"
        "The excerpts mention ASCII but not the value for '0'."
    )
    assert text.startswith("insufficient information\n\n")
    assert text.count("insufficient information") == 1
    assert support and "ASCII" in support
    assert not support.lower().startswith("insufficient information")


def test_strip_label_only():
    assert strip_abstain_label("insufficient information") == ""
    assert strip_abstain_label("Pages were empty") == "Pages were empty"
