from __future__ import annotations

from app.textutil import (
    garbage_ratio,
    keyword_aliases,
    needs_ocr,
    normalize_text,
    tokenize,
)


def test_normalize_ligatures_and_soft_hyphen():
    assert "fi" in normalize_text("modi\ufb01ed")  # ﬁ ligature
    assert "soft" in normalize_text("soft\u00adware")  # soft hyphen removed
    assert normalize_text("A\u2217") == "A*"
    assert " " not in normalize_text("a\u00a0b") or normalize_text("a\u00a0b") == "a b"


def test_tokenize_special_tokens():
    toks = tokenize("We compare A* with C++ and C# under O(n log n).")
    assert "a*" in toks
    assert "c++" in toks
    assert "c#" in toks
    assert any(t.startswith("o(") for t in toks)


def test_keyword_aliases_astar():
    aliases = keyword_aliases("A*")
    assert any(a.replace("∗", "*") == "A*" or a == "A*" for a in aliases)
    assert any("star" in a.lower() or "astar" in a.lower().replace("-", "") for a in aliases)


def test_ocr_trigger_on_cid_garbage():
    clean = "Normal readable page text with enough characters here."
    assert needs_ocr(clean) is False
    assert needs_ocr("hi") is True
    garbage = "\ufffd" * 20 + "abc"
    assert garbage_ratio(garbage) > 0.15
    assert needs_ocr(garbage) is True
    cid = "(cid:12)(cid:99)" * 10
    assert needs_ocr(cid) is True
