from __future__ import annotations

from app.agent.planner import _content_tokens, _heuristic_keywords, _is_usable_keyword
from app.query_nlp import QUERY_STOPWORDS, content_words, query_tokens
from app.textutil import tokenize


def test_nltk_stopwords_remove_filler_but_keep_policy_conditions():
    words = {w.lower() for w in content_words(
        "Please tell us whether we ourselves are not eligible except no items before or after 14 days."
    )}
    assert not words & {"please", "tell", "we", "ourselves", "are", "or"}
    assert {"not", "no", "except", "before", "after", "14", "eligible"} <= words
    assert "ourselves" in QUERY_STOPWORDS
    assert "ourselves" not in content_words("We ourselves. They apply.")


def test_nltk_query_tokens_preserve_technical_forms_and_order():
    tokens = query_tokens("Compare A∗, C++, C#, O(n log n), ISO-9001 and AI.")
    assert tokens == ["Compare", "A*", "C++", "C#", "O(nlogn)", "ISO-9001", "and", "AI"]
    assert query_tokens("A*search and policy_id") == ["A*", "search", "and", "policy_id"]


def test_planner_keeps_quoted_phrases_symbols_and_short_acronyms():
    assert _heuristic_keywords('What is the "right to cancel" in C++?')[:2] == [
        "right to cancel", "right",
    ]
    assert "C++" in _heuristic_keywords("Compare C++ and C#")
    assert {"ai", "ml", "path", "planning"} <= _content_tokens("AI and ML path planning")
    assert not _is_usable_keyword("the and ourselves", "What is AI?")
    assert _is_usable_keyword("AI", "What is AI?")


def test_stopwords_do_not_change_literal_document_tokens():
    # Stopword filtering is query planning only: exact phrases keep these tokens.
    assert {"not", "before", "after", "the", "and"} <= set(
        tokenize("not before and after the deadline")
    )


def test_word_tokenizer_needs_no_punkt_or_network(monkeypatch):
    import nltk

    def unexpected_download(*args, **kwargs):
        raise AssertionError("tokenization must not download resources")

    monkeypatch.setattr(nltk, "download", unexpected_download)
    monkeypatch.setattr(nltk.tokenize, "sent_tokenize", unexpected_download)
    assert query_tokens("Refunds are not allowed. Ask before Friday.") == [
        "Refunds", "are", "not", "allowed", "Ask", "before", "Friday",
    ]
