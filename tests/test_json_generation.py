from types import SimpleNamespace

import pytest

from app.llm.client import LLMClient, _parse_json
from app.agent import answerer


def test_gemini_primary_falls_back_to_groq():
    from app.config import LLM_MAX_ATTEMPTS, LLM_PRIMARY, REQUEST_DEADLINE_SEC

    client = LLMClient()
    client.primary = "gemini"
    chain = client._model_chain(light=False)
    assert chain[0].startswith("gemini/")
    assert any(model.startswith("groq/") for model in chain[1:])
    assert LLM_MAX_ATTEMPTS >= 2
    assert LLM_PRIMARY == "gemini"
    assert REQUEST_DEADLINE_SEC >= 20


def test_answer_uses_main_model_not_light_only(monkeypatch):
    seen = {}

    class _Fake:
        def complete_json(self, messages, **kwargs):
            seen.update(kwargs)
            return {"status": "insufficient_information", "answer": "no", "quotes": []}

    monkeypatch.setattr(answerer, "get_llm", lambda: _Fake())
    answerer.draft_answer(
        question="What is Voltix?",
        plan={},
        pages={3: "Voltix monitors energy use in legacy factories."},
        unused_candidates=[],
        budget_left=2,
    )
    assert seen.get("light") is False
    assert seen.get("max_attempts", 2) != 1


def test_json_generation_requests_provider_json_mode_once(monkeypatch):
    calls = []
    def complete(self, messages, **kwargs):
        calls.append(kwargs)
        return '{"status":"ok","answer":"A definition.","quotes":[{"id":"E1"}]}'
    monkeypatch.setattr(LLMClient, "complete", complete)
    result = LLMClient().complete_json([], max_attempts=1)
    assert result["status"] == "ok"
    assert len(calls) == 1
    assert calls[0]["json_mode"] is True
    assert calls[0]["max_attempts"] == 1


def test_escaped_quotes_and_newlines_parse():
    result = _parse_json(r'{"answer":"The product is \"Voltix\".\nIt monitors energy.","quotes":[{"id":"E1"}]}')
    assert '"Voltix"' in result["answer"]
    assert "\n" in result["answer"]


def test_malformed_json_is_not_repaired_or_accepted():
    with pytest.raises(ValueError):
        _parse_json('{"status":"ok","answer":"The "Voltix" system","quotes":[]}')


def test_invalid_generation_abstains_without_raw_parser_error(monkeypatch):
    calls = []
    def fail(*args, **kwargs):
        calls.append(kwargs)
        raise ValueError("JSONDecodeError: private provider response")
    monkeypatch.setattr(answerer, "get_llm", lambda: SimpleNamespace(complete_json=fail))
    result = answerer.draft_answer(question="What is Voltix?", plan={},
        pages={3: "Voltix monitors energy use in legacy factories."},
        unused_candidates=[], budget_left=2)
    assert result["status"] == "insufficient_information"
    assert result["quotes"] == []
    assert "JSONDecodeError" not in result["error"]
    assert len(calls) == 1
