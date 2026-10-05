from __future__ import annotations

from app.agent.evidence import build_evidence_spans, resolve_quote_refs
from app.agent.verifier import verify_quotes
from app.store.document_store import clean_page_text


def test_clean_page_text_strips_inline_toc_before_dehyphen():
    raw = (
        "A precise definition of artificial intelligence (AI) is not easy and often "
        "contro- 1.1 Brief history of AI 1\nversial. This introductory chapter outlines "
        "some areas associated with AI in a 1.2 Approaches to AI? 3\nhistorical context."
    )
    cleaned = clean_page_text(raw)
    assert "controversial" in cleaned
    assert "1.1 Brief history" not in cleaned
    assert "in a historical context" in cleaned.replace("\n", " ")


def test_clean_page_text_strips_watermark_fragments():
    raw = (
        "A W W WA\nVOLTIX - Master Product Document WATERM WATERM WATERMA RMARK\n"
        "Product name VoltixATERMARK W WATERMARK\nTeam Code Huntrix"
    )
    cleaned = clean_page_text(raw)
    assert "VOLTIX - Master Product Document" in cleaned
    assert "Voltix" in cleaned
    assert "WATERMARK" not in cleaned.upper()
    assert "ATERMARK" not in cleaned.upper()
    assert "Huntrix" in cleaned


def test_filter_headings_drops_watermark_junk():
    from app.store.document_store import Heading, _filter_headings

    raw = [
        Heading(title="WATERMARK WATERMARK", level=2, start=1, end=1),
        Heading(title="Field", level=3, start=1, end=1),
        Heading(title="Value", level=3, start=1, end=1),
        Heading(title="VOLTIX - Master Product Document", level=1, start=1, end=3),
        Heading(title="0.2 How to read this document", level=2, start=3, end=5),
        Heading(title="1", level=1, start=1, end=5),
    ]
    kept = _filter_headings(raw, page_count=100)
    titles = [h.title for h in kept]
    assert "VOLTIX - Master Product Document" in titles
    assert "0.2 How to read this document" in titles
    assert "Field" not in titles
    assert "Value" not in titles
    assert all("WATER" not in t.upper() for t in titles)


def test_evidence_ids_resolve_to_exact_verifiable_spans():
    pages = {
        1: (
            "A precise definition of artificial intelligence (AI) is not easy "
            "and often controversial. Many problems in AI can be formulated as search."
        )
    }
    spans = build_evidence_spans(pages)
    assert spans
    quotes = resolve_quote_refs([{"id": spans[0]["id"]}], {s["id"]: s for s in spans})
    ok, failures = verify_quotes(quotes, pages)
    assert ok is True
    assert failures == []
