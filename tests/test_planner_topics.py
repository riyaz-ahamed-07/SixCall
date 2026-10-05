from __future__ import annotations

from app.agent.planner import _prepend_topic_keywords, plan_question


def test_prepend_csv_json_before_broad_terms():
    keywords = _prepend_topic_keywords(
        "Write a program that parses CSV and produce JSON output",
        ["Processing Files", "File Input"],
    )
    assert keywords[0] == "Comma Separated Values"
    assert "CSV" in keywords
    assert "JSON" in keywords


def test_sample_code_keywords():
    keywords = _prepend_topic_keywords(
        "give sample code for operators",
        ["Operators"],
    )
    assert keywords[0] == "Operators"
    assert "Code Sample" in keywords
    assert "Algorithm" in keywords


def test_plan_question_sample_code_is_coding():
    headings = [
        {"title": "2.3. Operators", "start": 33, "end": 40},
        {"title": "2. Basics", "start": 20, "end": 50},
    ]
    plan = plan_question("give sample code for operators", headings)
    assert plan["intent"] == "howto"
    assert plan.get("coding") is True
    assert plan["keywords"][0].lower() in {"operators", "operator"}


def test_plan_question_csv_exercise():
    headings = [
        {"title": "9.1. Processing Files", "start": 185, "end": 190},
        {"title": "9. File Input/Output", "start": 183, "end": 200},
    ]
    q = (
        "Write a program that parses and processes a data file containing "
        "Comma Separated Values (CSV) and produce an equivalent JSON output file"
    )
    plan = plan_question(q, headings)
    kws = [k.lower() for k in plan["keywords"]]
    assert any("csv" in k or "comma separated" in k for k in kws)
    assert plan["intent"] == "howto"
