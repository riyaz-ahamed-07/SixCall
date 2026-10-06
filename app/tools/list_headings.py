from __future__ import annotations

from typing import Any

from app.agent.schemas import ListHeadingsArgs
from app.store.document_store import get_store
from app.tools.wrapper import require_active_session


def list_headings(doc_id: str) -> list[dict[str, Any]]:
    """Return TOC / headings only for a document. Requires active session."""
    ListHeadingsArgs(doc_id=doc_id)
    session = require_active_session()
    store = get_store()
    return session.call("list_headings", store.list_headings, doc_id=doc_id)
