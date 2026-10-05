from __future__ import annotations

from app.agent.overview import is_overview_question, select_overview_pages


def test_overview_question_detection():
    assert is_overview_question("What is this document about?")
    assert is_overview_question("Give a summary")
    assert is_overview_question("Summarize this PDF")
    assert is_overview_question("Summarize the document")
    assert is_overview_question("tl;dr")
    assert not is_overview_question("What is the refund window?")
    assert not is_overview_question("Prove A* optimality")
    # Topic-specific summaries must use the keyword agent, not overview sampling.
    assert not is_overview_question("Summarize the refund policy")
    assert not is_overview_question("Give a summary of the cancellation clause")


def test_select_overview_pages_intro_major_conclusion():
    headings = [
        {"title": "Abstract", "level": 1, "start": 1, "end": 1},
        {"title": "1 Introduction", "level": 1, "start": 2, "end": 4},
        {"title": "2 Methods", "level": 1, "start": 5, "end": 10},
        {"title": "2.1 Setup", "level": 2, "start": 6, "end": 7},
        {"title": "3 Results", "level": 1, "start": 11, "end": 15},
        {"title": "4 Conclusion", "level": 1, "start": 16, "end": 17},
        {"title": "Fig. 1 Example", "level": 1, "start": 9, "end": 9},
    ]
    pages = select_overview_pages(headings, page_count=17)
    assert len(pages) <= 5
    assert 1 in pages  # abstract
    assert 16 in pages  # conclusion
    assert all(p >= 1 for p in pages)
    assert len(pages) == len(set(pages))


def test_select_overview_pages_empty_defaults_to_page_one():
    assert select_overview_pages([], page_count=1) == [1]


def test_select_overview_pages_no_headings_samples_across_doc():
    pages = select_overview_pages([], page_count=20)
    assert len(pages) <= 5
    assert 1 in pages
    assert 20 in pages
    assert len(pages) == len(set(pages))
    assert max(pages) == 20
