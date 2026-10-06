from __future__ import annotations

import json
import logging
import os
import re
import time
import warnings
from typing import Any

from app.config import (
    GEMINI_MODEL,
    GEMINI_MODEL_LIGHT,
    GROQ_MODEL,
    GROQ_MODEL_FAST,
    LLM_ATTEMPT_TIMEOUT_SEC,
    LLM_MAX_ATTEMPTS,
    LLM_PRIMARY,
    load_config,
)
from app.deadline import (
    DeadlineExceededError,
    attempt_timeout,
    check_deadline,
)

load_config()

logger = logging.getLogger(__name__)

# Quiet LiteLLM's noisy "Give Feedback / Get Help" banners on failed attempts
logging.getLogger("LiteLLM").setLevel(logging.ERROR)
logging.getLogger("litellm").setLevel(logging.ERROR)
os.environ.setdefault("LITELLM_LOG", "ERROR")
warnings.filterwarnings("ignore", message=".*temperature.*Gemini.*")

_TRANSIENT = (
    "ServiceUnavailableError",
    "RateLimitError",
    "APIConnectionError",
    "Timeout",
    "InternalServerError",
)


class LLMClient:
    """Groq/Gemini via LiteLLM. Order controlled by LLM_PRIMARY (default: groq)."""

    def __init__(self) -> None:
        self.gemini_main = f"gemini/{GEMINI_MODEL}"
        self.gemini_light = f"gemini/{GEMINI_MODEL_LIGHT}"
        self.groq_main = f"groq/{GROQ_MODEL}"
        self.groq_fast = f"groq/{GROQ_MODEL_FAST}"
        self._gemini_key_i = 0
        self._groq_key_i = 0
        self.primary = (LLM_PRIMARY or "groq").strip().lower()
        self.last_attempts: list[dict[str, Any]] = []

    def _model_chain(self, *, light: bool) -> list[str]:
        gemini = self.gemini_light if light else self.gemini_main
        if self.primary in {"groq", "grok"}:
            chain = [
                self.groq_fast if light else self.groq_main,
                self.groq_main if light else self.groq_fast,
                gemini,
            ]
        else:
            chain = [gemini, self.groq_main, self.groq_fast]
        seen: set[str] = set()
        out: list[str] = []
        for m in chain:
            if m not in seen:
                seen.add(m)
                out.append(m)
        return out

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        json_mode: bool = False,
        light: bool = False,
        max_attempts: int | None = None,
    ) -> str:
        models = self._model_chain(light=light)
        seen: set[str] = set()
        ordered = []
        for m in models:
            if m not in seen:
                seen.add(m)
                ordered.append(m)

        limit = LLM_MAX_ATTEMPTS if max_attempts is None else max(1, int(max_attempts))
        self.last_attempts = []
        last_err: Exception | None = None
        attempts = 0

        for model in ordered:
            if attempts >= limit:
                break
            check_deadline()
            keys = self._keys_for(model)
            if not keys:
                continue
            key = keys[0]
            attempts += 1
            started = time.monotonic()
            try:
                text = self._call(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    json_mode=json_mode,
                    api_key=key,
                )
                self.last_attempts.append(
                    {
                        "model": model,
                        "ok": True,
                        "elapsed_ms": int((time.monotonic() - started) * 1000),
                    }
                )
                logger.info("llm OK model=%s elapsed_ms=%.0f", model, (time.monotonic() - started) * 1000)
                return text
            except DeadlineExceededError:
                self.last_attempts.append(
                    {
                        "model": model,
                        "ok": False,
                        "error": "deadline_exceeded",
                        "elapsed_ms": int((time.monotonic() - started) * 1000),
                    }
                )
                raise
            except Exception as exc:
                last_err = exc
                self.last_attempts.append(
                    {
                        "model": model,
                        "ok": False,
                        "error": f"{type(exc).__name__}",
                        "elapsed_ms": int((time.monotonic() - started) * 1000),
                    }
                )
                logger.info(
                    "llm FAIL model=%s err=%s elapsed_ms=%.0f",
                    model,
                    type(exc).__name__,
                    (time.monotonic() - started) * 1000,
                )
                if _is_transient(exc) and attempts < limit:
                    time.sleep(0.05)
                    continue
                # Non-transient: do not burn remaining attempts on same failure class
                # unless we still have attempt budget for a different model.
                continue

        if last_err is not None:
            raise RuntimeError(f"LLM unavailable: {last_err}") from last_err
        raise RuntimeError("LLM unavailable: no API keys configured")

    def complete_json(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.1,
        light: bool = True,
        max_attempts: int | None = None,
    ) -> dict[str, Any]:
        # Strict judging: local parse only — no repair LLM call.
        raw = self.complete(
            messages,
            temperature=temperature,
            json_mode=True,
            light=light,
            max_attempts=max_attempts,
        )
        return _parse_json(raw)

    def _keys_for(self, model: str) -> list[str]:
        if model.startswith("gemini/"):
            keys = _collect_keys("GEMINI_API_KEY", "GOOGLE_API_KEY")
            if not keys:
                return []
            i = self._gemini_key_i % len(keys)
            self._gemini_key_i += 1
            return keys[i:] + keys[:i]
        if model.startswith("groq/"):
            keys = _collect_keys("GROQ_API_KEY")
            if not keys:
                return []
            i = self._groq_key_i % len(keys)
            self._groq_key_i += 1
            return keys[i:] + keys[:i]
        return []

    def _call(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        json_mode: bool,
        api_key: str,
    ) -> str:
        from litellm import completion

        check_deadline()
        timeout = attempt_timeout(LLM_ATTEMPT_TIMEOUT_SEC, floor=1.0)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "api_key": api_key,
            "timeout": timeout,
            "num_retries": 0,
            "max_tokens": 1200,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        resp = completion(**kwargs)
        if getattr(resp.choices[0], "finish_reason", None) == "length":
            raise ValueError("model output exceeded its token limit")
        content = resp.choices[0].message.content
        if content is None:
            raise RuntimeError("empty LLM response")
        return str(content)


_LLM: LLMClient | None = None


def get_llm() -> LLMClient:
    global _LLM
    if _LLM is None:
        _LLM = LLMClient()
    return _LLM


def reset_llm_for_tests() -> None:
    global _LLM
    _LLM = None


def _collect_keys(*primary: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for base in primary:
        for name, val in os.environ.items():
            if name == base or name.startswith(base + "_"):
                v = (val or "").strip()
                if v and v not in seen:
                    seen.add(v)
                    found.append(v)
    numbered = []
    plain = []
    for base in primary:
        for name, val in os.environ.items():
            v = (val or "").strip()
            if not v or v not in seen:
                continue
            if name.startswith(base + "_") and name[len(base) + 1 :].isdigit():
                numbered.append((int(name.split("_")[-1]), v))
            elif name == base:
                plain.append(v)
    if numbered:
        numbered.sort()
        ordered = [v for _, v in numbered]
        for v in plain:
            if v not in ordered:
                ordered.append(v)
        for v in found:
            if v not in ordered:
                ordered.append(v)
        return ordered
    return found


def _is_transient(exc: Exception) -> bool:
    name = type(exc).__name__
    msg = str(exc).lower()
    if name in _TRANSIENT:
        return True
    return any(
        s in msg
        for s in ("503", "429", "high demand", "rate limit", "unavailable", "timeout")
    )


def _parse_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        data = json.loads(fence.group(1))
        if isinstance(data, dict):
            return data

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        data = json.loads(text[start : end + 1])
        if isinstance(data, dict):
            return data
    raise ValueError(f"could not parse JSON from LLM: {text[:200]!r}")
