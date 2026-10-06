"""Small shapes for plans, drafts, spans, and ask results.

Bad model JSON fails here, before the loop treats it as evidence.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EvidenceSpan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(pattern=r"^E\d+$")
    page: int = Field(ge=1)
    text: str = Field(min_length=1)
    genre: str = "prose"


class QuoteRef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    evidence_id: str | None = None
    text: str | None = None
    page: int | None = None


class Plan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    rewritten: str = ""
    qtype: Literal["fact", "multi", "compare", "absent"] = "fact"
    keywords: list[str] = Field(default_factory=list)
    heading_hints: list[str] = Field(default_factory=list)
    contradiction_sensitive: bool = False
    intent: str | None = None
    format_card: str = ""

    @field_validator("qtype", mode="before")
    @classmethod
    def _qtype(cls, value: Any) -> str:
        kind = str(value or "fact").lower()
        if kind not in {"fact", "multi", "compare", "absent"}:
            return "fact"
        return kind


class AnswerDraft(BaseModel):
    """Model JSON for one answer call. Unknown status becomes an abstain."""

    model_config = ConfigDict(extra="ignore")

    status: Literal["ok", "insufficient_information"] = "insufficient_information"
    answer: str = ""
    quotes: list[QuoteRef] = Field(default_factory=list)

    @field_validator("status", mode="before")
    @classmethod
    def _status(cls, value: Any) -> str:
        kind = str(value or "insufficient_information").lower()
        if kind not in {"ok", "insufficient_information"}:
            return "insufficient_information"
        return kind

    @field_validator("answer", mode="before")
    @classmethod
    def _answer(cls, value: Any) -> str:
        return "" if value is None else str(value)


class AskResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str
    status: Literal["ok", "insufficient_information"]
    pages_used: list[int] = Field(default_factory=list)
    tool_trace: list[dict[str, Any]] = Field(default_factory=list)
    calls_used: int = 0
    question_id: str = ""
    reason: str | None = None
    status_reason: str | None = None
    quotes: list[dict[str, Any]] = Field(default_factory=list)
    intent: str | None = None
    strategy: str | None = None
    timing: dict[str, Any] | None = None
    evidence_cleared: bool | None = None


class ListHeadingsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str = Field(min_length=1)


class SearchKeywordArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str = Field(min_length=1)
    keyword: str | list[str]

    @field_validator("keyword", mode="before")
    @classmethod
    def _keyword(cls, value: Any) -> str | list[str]:
        if isinstance(value, (list, tuple)):
            pins = [str(item).strip() for item in value if str(item or "").strip()]
            if not pins:
                raise ValueError("keyword list must not be empty")
            return pins
        text = str(value or "").strip()
        if not text:
            raise ValueError("keyword must not be blank")
        return text


class GetPageArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str = Field(min_length=1)
    page_number: int = Field(ge=1)

    @field_validator("page_number", mode="before")
    @classmethod
    def _page(cls, value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("page_number must be int")
        return value
