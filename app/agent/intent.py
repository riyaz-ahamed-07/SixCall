from __future__ import annotations

import re
from typing import Any, Literal

Intent = Literal["define", "prove", "compare", "multi", "howto", "fact", "absent"]

# Hardcoded format cards — cheap, explainable, no extra LLM call.
_FORMAT: dict[Intent, str] = {
    "define": (
        "FORMAT=define: 3–5 sentences. Give the definition plus key supporting ideas "
        "present in the excerpts (setting, constraints, how it is set up). "
        "Do not invent. Prefer 2–4 short quotes covering different points."
    ),
    "prove": (
        "FORMAT=prove: Explain the argument in order (assumptions → key steps → conclusion). "
        "3–6 sentences. Quote the critical statements (theorem, definition, final claim)."
    ),
    "compare": (
        "FORMAT=compare: Contrast the items explicitly (A vs B). "
        "Use short paragraphs or 'A: … / B: …'. Quote evidence for each side."
    ),
    "multi": (
        "FORMAT=multi: Cover each part of the question. Use a short numbered list (1. 2. 3.) "
        "if helpful. One quote per major point when possible."
    ),
    "howto": (
        "FORMAT=howto: Give ordered steps the document describes. "
        "Keep steps faithful to the excerpts; quote key procedural lines. "
        "If excerpts include source code, pseudocode, or Code Sample blocks, "
        "include those lines in the answer (do not invent APIs) and cite evidence ids. "
        "If the question restates an exercise, summarize the exercise requirements "
        "and any example I/O from the excerpts when a full solution is not shown."
    ),
    "fact": (
        "FORMAT=fact: 2–4 sentences answering directly with the needed detail from excerpts. "
        "Include supporting context only if present. "
        "Pseudocode and Code Sample lines in excerpts count as sample code when asked."
    ),
    "absent": (
        "FORMAT=absent: If excerpts lack the answer, status=insufficient_information. "
        "Do not guess."
    ),
}

_QTYPE_TO_INTENT: dict[str, Intent] = {
    "fact": "fact",
    "multi": "multi",
    "compare": "compare",
    "absent": "absent",
}


def resolve_intent(question: str, qtype: str | None = None) -> Intent:
    """Map question (+ optional planner qtype) to a hardcoded intent card."""
    q = (question or "").lower().strip()
    qt = (qtype or "").lower().strip()

    if _looks_absent(q) or qt == "absent":
        return "absent"
    if _looks_compare(q) or qt == "compare":
        return "compare"
    if _looks_prove(q):
        return "prove"
    if _looks_howto(q) or _looks_code_example(q) or _looks_pseudocode(q):
        return "howto"
    if _looks_define(q):
        return "define"
    if qt == "multi" or _looks_multi(q):
        return "multi"
    if qt in _QTYPE_TO_INTENT:
        return _QTYPE_TO_INTENT[qt]
    return "fact"


def format_card(intent: Intent) -> str:
    return _FORMAT[intent]


def is_coding_question(question: str) -> bool:
    """True for sample-code / program / pseudocode asks (coding answer path)."""
    q = (question or "").lower().strip()
    if not q:
        return False
    return _looks_howto(q) or _looks_code_example(q) or _looks_pseudocode(q)


def attach_intent(plan: dict[str, Any], question: str) -> dict[str, Any]:
    intent = resolve_intent(question, str(plan.get("qtype") or ""))
    out = dict(plan)
    out["intent"] = intent
    out["format_card"] = format_card(intent)
    out["coding"] = is_coding_question(question)
    return out


def _looks_define(q: str) -> bool:
    return bool(
        re.search(
            r"\b(what is|what's|define|definition of|explain|meaning of|describe)\b",
            q,
        )
    )


def _looks_prove(q: str) -> bool:
    return bool(
        re.search(
            r"\b(prove|proof|show that|why (is|are|does)|derive|justify)\b",
            q,
        )
    )


def _looks_compare(q: str) -> bool:
    return bool(
        re.search(r"\b(compare|difference|vs\.?|versus|contrast|better than)\b", q)
    )


def _looks_code_example(q: str) -> bool:
    return bool(
        re.search(
            r"\b("
            r"sample code|code sample|code snippet|example code|"
            r"show (me )?code|give (me )?(the )?code|"
            r"give (me )?(those |the )?(conceptual )?(pseudocode|illustrations?)"
            r")\b",
            q,
        )
    )


def _looks_pseudocode(q: str) -> bool:
    return bool(re.search(r"\b(pseudocode|pseudo[\s-]?code)\b", q))


def _looks_howto(q: str) -> bool:
    return bool(
        re.search(
            r"\b("
            r"how (do|to|can|does)|steps to|procedure|algorithm for|"
            r"write (a |an )?(program|function|code|script)|"
            r"implement|parse|convert|produce .* output"
            r")\b",
            q,
        )
    )


def _looks_multi(q: str) -> bool:
    return bool(re.search(r"\b(and also|as well as|list|both)\b", q)) or q.count("?") > 1


def _looks_absent(q: str) -> bool:
    return bool(
        re.search(r"\b(is there any|does it mention|is it stated|anything about)\b", q)
    )
