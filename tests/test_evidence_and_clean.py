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


def test_scrubber_keeps_real_tokens():
    raw = (
        "The committee ate lunch and will update the late schedule. "
        "Please create a date for the water test."
    )
    cleaned = clean_page_text(raw).lower()
    for word in ("ate", "update", "late", "create", "date", "water", "test"):
        assert word in cleaned


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


def test_later_page_is_not_starved_by_early_spans():
    page1 = " ".join(
        f"Sentence number {i} discusses shipping policy details." for i in range(30)
    )
    pages = {
        1: page1,
        2: "The amendment supersedes the prior refund window of thirty days.",
    }
    spans = build_evidence_spans(pages)
    assert any(s["page"] == 2 and "supersedes" in s["text"] for s in spans)
    page1_count = sum(1 for s in spans if s["page"] == 1)
    assert page1_count <= 12


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


def test_extend_quotes_lengthens_short_citation():
    from app.agent.evidence import extend_quotes

    pages = {
        1: (
            "Numerical operators allow you to create complex expressions involving "
            "either numerical literals and/or numerical variables. The unary negation "
            "operator allows you to negate a numerical literal or variable."
        )
    }
    short = [{"text": "Numerical operators allow you", "page": 1}]
    extended = extend_quotes(short, pages)
    assert len(extended[0]["text"].split()) > len(short[0]["text"].split())
    ok, failures = verify_quotes(extended, pages)
    assert ok is True
    assert failures == []


def test_evidence_keeps_code_lines_intact():
    pages = {
        1: (
            "Write a CSV to JSON converter.\n"
            "  FILE *in = fopen(\"data.csv\", \"r\");\n"
            "  while (fgets(buf, sizeof(buf), in)) {\n"
            "    printf(\"%s\\n\", buf);\n"
            "  }\n"
            "Then close the file."
        )
    }
    spans = build_evidence_spans(pages)
    texts = [s["text"] for s in spans]
    assert any("fopen" in t for t in texts)
    assert any("fgets" in t for t in texts)
    code_quote = next(t for t in texts if "fopen" in t)
    ok, failures = verify_quotes([{"text": code_quote, "page": 1}], pages)
    assert ok is True
    assert failures == []


def test_repair_quotes_maps_paraphrase_to_code_span():
    from app.agent.evidence import repair_quotes

    pages = {
        1: 'int main(void) {\n  FILE *fp = fopen("a.csv", "r");\n  return 0;\n}\n'
    }
    repaired = repair_quotes(
        [{"text": "open a.csv with fopen", "page": 1}],
        pages,
    )
    assert repaired
    ok, failures = verify_quotes(repaired, pages)
    assert ok is True
    assert failures == []
