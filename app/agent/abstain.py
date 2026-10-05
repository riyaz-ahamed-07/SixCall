from __future__ import annotations

_LABEL = "insufficient information"


def strip_abstain_label(text: str) -> str:
    """Remove a leading abstain label so callers can re-apply it once."""
    s = (text or "").strip()
    if not s:
        return ""
    low = s.lower()
    if low == _LABEL:
        return ""
    if low.startswith(_LABEL):
        rest = s[len(_LABEL) :].lstrip(" \t\r\n:.-")
        return rest.strip()
    return s


def format_abstain_text(detail: str | None) -> tuple[str, str | None]:
    """Return (display_text, support_reason) with the label only once."""
    support = strip_abstain_label(detail or "")
    if not support or support.lower() in {_LABEL, "model declined"}:
        return _LABEL, support or None
    return f"{_LABEL}\n\n{support}", support
