from __future__ import annotations

from app.agent.scorer import score_pages


def test_prefer_early_ranks_opening_pages_first():
    ranked = score_pages(
        keyword_hits={"computer science": [1, 2, 249, 589]},
        headings=[
            {"title": "Introduction", "start": 1, "end": 16},
            {"title": "14. Introduction to Databases", "start": 249, "end": 249},
        ],
        heading_hints=[],
        contradiction_sensitive=False,
        top_k=2,
        prefer_early=True,
    )
    assert ranked[0] in {1, 2}
    assert 249 not in ranked[:2]


def test_heading_match_does_not_flood_full_section():
    from app.agent.scorer import _pages_in_heading_hints

    pages = _pages_in_heading_hints(
        [{"title": "Introduction", "start": 1, "end": 16}],
        ["Introduction"],
        {"Introduction": [1, 2, 14]},
    )
    assert 1 in pages
    assert 2 in pages
    assert len(pages) <= 4
