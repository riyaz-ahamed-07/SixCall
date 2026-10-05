from __future__ import annotations

from app.agent.intent import resolve_intent
from app.agent.scorer import score_pages


def test_intent_router_define_prove_compare():
    assert resolve_intent("What is path planning in robotics?") == "define"
    assert resolve_intent("Prove A* optimality") == "prove"
    assert resolve_intent("Compare DFS and BFS") == "compare"
    assert resolve_intent("How do we build the configuration space?") == "howto"
    assert resolve_intent("Does it mention teleportation?", "absent") == "absent"


def test_scorer_prefers_tree_and_keyword_intersection():
    headings = [
        {"title": "Path planning", "level": 2, "start": 9, "end": 9},
        {
            "title": "Fig. 2.4 (a) A path planning problem,",
            "level": 3,
            "start": 12,
            "end": 12,
        },
        {"title": "Other", "level": 2, "start": 40, "end": 42},
    ]
    hits = {
        "Path planning": [7, 9, 12, 35, 37],
        "Robotics": list(range(1, 50)),
    }
    ranked = score_pages(
        keyword_hits=hits,
        headings=headings,
        heading_hints=["Path planning"],
        contradiction_sensitive=False,
        top_k=3,
    )
    assert ranked[0] == 9


def test_scorer_expands_heading_range_for_section():
    headings = [
        {"title": "Optimality of A*search", "level": 1, "start": 23, "end": 25},
    ]
    hits = {"A*": [23]}
    ranked = score_pages(
        keyword_hits=hits,
        headings=headings,
        heading_hints=["Optimality of A*search"],
        contradiction_sensitive=False,
        top_k=3,
    )
    assert 23 in ranked and 25 in ranked


def test_contradiction_puts_latest_keyword_hit_first():
    headings = [
        {"title": "Refund policy", "level": 1, "start": 2, "end": 5},
    ]
    hits = {"refund": [2, 3, 40], "policy": [2, 6]}
    ranked = score_pages(
        keyword_hits=hits,
        headings=headings,
        heading_hints=["Refund policy"],
        contradiction_sensitive=True,
        top_k=3,
    )
    assert ranked[0] == 40
    assert 40 in ranked[:3]
