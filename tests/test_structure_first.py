"""Structure-first navigation: question-only pins, dual index, one optional TOC pick."""

from __future__ import annotations

from app.agent.loop import run_agent
from app.agent.navigate import (
    SectionMatch,
    apply_supersede_lock,
    choose_pages,
    match_sections,
    optional_search_keeps_repair,
)
from app.agent.pins import extract_pins, extract_question, term_allowed, term_in_question
from app.agent.toc_pick import accept_toc_pick
from app.index.dual_index import build_precision_index
from app.store.document_store import (
    DocRecord,
    Heading,
    build_inverted_index,
    reset_store_for_tests,
)
from app.store.section_tree import lexical_heading_candidates
from app.tools.wrapper import clear_active_session, start_question


def test_pins_are_substrings_and_do_not_invent_expansions():
    question = "What is AI?"
    pins = extract_pins(question)
    assert pins
    assert all(term_in_question(pin, question) for pin in pins)
    assert all("artificial" not in pin.lower() for pin in pins)
    longer = "What is the latest refund window after the amendment?"
    again = extract_pins(longer)
    assert "refund window" in [p.lower() for p in again]
    assert "amendment" in [p.lower() for p in again]
    assert all(term_in_question(pin, longer) for pin in again)


def test_accept_toc_pick_drops_terms_not_in_the_extract():
    picked = accept_toc_pick(
        {
            "sections": ["n0", "Not in the outline"],
            "use_terms": ["Artificial Intelligence", "AI"],
        },
        [{"title": "Battery", "start": 1, "end": 1, "level": 1}],
        ["AI"],
    )
    assert picked["use_terms"] == ["AI"]
    assert picked["sections"] == ["n0"]
    assert [h["title"] for h in picked["headings"]] == ["Battery"]


def test_extract_records_quotes_clauses_capwords_and_supersede():
    question = 'What does clause 4.2 say about the "refund window" after the amendment?'
    extract = extract_question(question)
    assert extract.supersede
    assert any("4.2" in item for item in extract.clause_ids)
    assert "refund window" in [item.lower() for item in extract.quotes]
    assert "what" not in [item.lower() for item in extract.capwords]
    assert all(term_in_question(term, question) for term in extract.terms)
    days = extract_question("The limit is 14 days.")
    assert "14" in days.numbers
    assert all("14 days" not in item.lower() for item in days.clause_ids)
    dated = extract_question("What changed on 2024-01-15 except the freight rule?")
    assert "2024-01-15" in dated.dates
    assert "except" in dated.negations
    assert dated.supersede is False
    updated = extract_question("What is the current update to clause 7.2?")
    assert updated.supersede
    assert any("update" in cue.lower() for cue in updated.supersede_cues)
    assert any("7.2" in item for item in updated.clause_ids)
    assert term_allowed("clause 7.2", updated)
    assert term_allowed("battery chemistry", updated) is False


def test_match_sections_keeps_at_most_three_ranges():
    headings = [
        {"title": f"Refund policy {i}", "start": i, "end": i, "level": 1}
        for i in range(1, 6)
    ]
    matched = match_sections("What is the refund policy?", headings, ["refund policy"])
    assert matched.strong
    assert len(matched.headings) == 3
    assert len(matched.ranges) == 3


def test_supersede_lock_replaces_lowest_page_when_the_window_is_full():
    # Later statement supersedes earlier.
    locked = apply_supersede_lock([2, 3, 4], 40)
    assert locked == [2, 3, 40]
    assert apply_supersede_lock([2, 40], 40) == [2, 40]
    assert optional_search_keeps_repair(3) is True
    assert optional_search_keeps_repair(2) is False


def test_supersede_lock_keeps_latest_hit_outside_the_section():
    ranked = choose_pages(
        keyword_hits={"refund": [2, 3, 40]},
        sections=SectionMatch(strong=True, headings=[], ranges=[(2, 5)], starts=[2]),
        supersede=True,
        ensure_each_hit=False,
        top_k=3,
    )
    assert ranked[0] == 40
    assert 2 in ranked[:3]


def test_lexical_headings_when_lines_look_like_an_outline():
    pages = {
        1: "1.1 Refund policy\nThe body of the section is a normal sentence.",
        2: "1.2 Shipping policy\nAnother sentence about fees.",
    }
    titles = [title for _level, title, _page in lexical_heading_candidates(pages)]
    assert any("Refund policy" in title for title in titles)
    assert any("Shipping policy" in title for title in titles)


def test_precision_phrase_and_number_then_recall_for_stems(tmp_path):
    pages = {
        1: "The refund window is 14 days.",
        2: "A refunds desk sits beside a window sign.",
        3: "The team is running the drill today.",
        4: "Operators run the drill tomorrow.",
    }
    store = reset_store_for_tests(tmp_path / "docs")
    rec = DocRecord(
        doc_id="idxidxidxidxidx1",
        meta={"page_count": 4, "title": "notes"},
        pages=pages,
        labels={},
        headings=[],
        index=build_inverted_index(pages),
        precision_index=build_precision_index(pages),
    )
    store._docs[rec.doc_id] = rec
    assert store.search_keyword(rec.doc_id, "refund window") == [1]
    assert store.search_keyword(rec.doc_id, "14") == [1]
    assert store.search_keyword(rec.doc_id, "140") == []
    stemmed = store.search_keyword(rec.doc_id, "running")
    assert stemmed == [3, 4]
    assert all(isinstance(p, int) for p in stemmed)


def test_happy_path_skips_planner_when_headings_overlap(tmp_path, monkeypatch):
    clear_active_session()
    pages = {1: "The refund window is 14 days for unused items."}
    store = reset_store_for_tests(tmp_path / "docs")
    rec = DocRecord(
        doc_id="abcd1234abcd1234",
        meta={"page_count": 1, "title": "policy"},
        pages=pages,
        labels={},
        headings=[Heading(title="Refund window", level=1, start=1, end=1)],
        index=build_inverted_index(pages),
        precision_index=build_precision_index(pages),
    )
    store._docs[rec.doc_id] = rec
    called: list[str] = []

    def _boom(question, headings):
        called.append(question)
        raise AssertionError("planner must stay off when headings overlap")

    monkeypatch.setattr("app.agent.loop.pick_toc", _boom)

    def _draft(**kwargs):
        return {
            "status": "ok",
            "answer": "The refund window is 14 days.",
            "quotes": [{"text": "The refund window is 14 days for unused items.", "page": 1}],
        }

    monkeypatch.setattr("app.agent.loop.draft_answer", _draft)
    result = run_agent(rec.doc_id, "What is the refund window?")
    assert called == []
    assert result["status"] == "ok"
    assert result["timing"]["planner_used"] is False
    assert result["timing"]["planner_llm"] == 0
    assert result["timing"]["toc_llm"] == 0
    assert result["timing"]["llm_calls"] == 1
    assert result["calls_used"] > 0
    assert "elapsed_ms" in result["tool_trace"][0]
    clear_active_session()


def test_weak_overlap_calls_planner_once_and_keeps_question_terms(tmp_path, monkeypatch):
    clear_active_session()
    pages = {2: "The lunar freight warranty lasts five years from shipment."}
    store = reset_store_for_tests(tmp_path / "docs")
    rec = DocRecord(
        doc_id="abcd1234abcd1234",
        meta={"page_count": 2, "title": "policy"},
        pages=pages,
        labels={},
        headings=[Heading(title="Battery capacity", level=1, start=1, end=1)],
        index=build_inverted_index(pages),
        precision_index=build_precision_index(pages),
    )
    store._docs[rec.doc_id] = rec
    calls = {"n": 0}

    def _pick(question, headings, allowed_terms):
        calls["n"] += 1
        return {
            "sections": ["n0", "Invented heading"],
            "use_terms": ["lunar freight", "battery chemistry"],
        }

    monkeypatch.setattr("app.agent.loop.pick_toc", _pick)

    def _draft(**kwargs):
        assert 2 in kwargs["pages"]
        return {
            "status": "ok",
            "answer": "The lunar freight warranty lasts five years.",
            "quotes": [{"text": "The lunar freight warranty lasts five years from shipment.", "page": 2}],
        }

    monkeypatch.setattr("app.agent.loop.draft_answer", _draft)
    result = run_agent(rec.doc_id, "What is the lunar freight warranty?")
    searched = [
        step["args"].get("keyword")
        for step in result["tool_trace"]
        if step["tool"] == "search_keyword"
    ]
    assert result["status"] == "ok"
    assert calls["n"] == 1
    assert result["timing"]["planner_used"] is True
    assert result["timing"]["llm_calls"] == 2
    assert searched
    assert all("battery" not in str(kw).lower() for kw in searched)
    assert all(term_in_question(str(kw), "What is the lunar freight warranty?") for kw in searched)
    assert all(term_allowed(str(kw), extract_question("What is the lunar freight warranty?")) for kw in searched)
    clear_active_session()


def test_flat_outline_extra_search_keeps_the_repair_slot(tmp_path, monkeypatch):
    clear_active_session()
    quote = "The refund window is 14 days."
    pages = {
        1: f"Refund window section. {quote}",
        2: "Shipping fee section. The shipping fee is five dollars.",
        3: f"More background about the refund window. {quote}",
        4: f"Still more background about the refund window. {quote}",
        5: f"Later background about the refund window. {quote}",
        6: f"Last background about the refund window. {quote}",
    }
    store = reset_store_for_tests(tmp_path / "docs")
    rec = DocRecord(
        doc_id="abcd1234abcd1234",
        meta={"page_count": 6, "title": "policy"},
        pages=pages,
        labels={},
        headings=[Heading(title="Refund window", level=1, start=1, end=2)],
        index=build_inverted_index(pages),
        precision_index=build_precision_index(pages),
    )
    store._docs[rec.doc_id] = rec
    question = "What is the refund window for the shipping fee?"
    extract = extract_question(question)
    calls = {"n": 0}

    def _boom(*args, **kwargs):
        raise AssertionError("strong overlap must not call a TOC model")

    monkeypatch.setattr("app.agent.loop.pick_toc", _boom)

    def _draft(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            assert kwargs["budget_left"] >= 1
            assert kwargs["unused_candidates"]
            return {
                "status": "insufficient_information",
                "answer": "Need one more page.",
                "quotes": [],
            }
        page = max(kwargs["pages"])
        return {
            "status": "ok",
            "answer": quote,
            "quotes": [{"text": quote, "page": page}],
        }

    monkeypatch.setattr("app.agent.loop.draft_answer", _draft)
    result = run_agent(rec.doc_id, question)
    searched = [
        step["args"].get("keyword")
        for step in result["tool_trace"]
        if step["tool"] == "search_keyword"
    ]
    fetched = [
        step["args"].get("page_number")
        for step in result["tool_trace"]
        if step["tool"] == "get_page"
    ]
    assert result["status"] == "ok"
    assert result["timing"]["planner_llm"] == 0
    assert calls["n"] == 2
    assert len(searched) == 2
    assert len(fetched) >= 2
    assert result["calls_used"] <= 6
    assert all(term_allowed(str(kw), extract) for kw in searched)
    clear_active_session()


def test_tool_log_records_elapsed_ms():
    clear_active_session()
    session = start_question("q-time", max_calls=6)
    try:
        session.call("list_documents", lambda: [{"doc_id": "x"}])
        assert session.trace[-1].elapsed_ms >= 0
        assert "elapsed_ms" in session.trace[-1].as_dict()
        assert "budget_left=" in session.trace[-1].result_summary
    finally:
        clear_active_session()
