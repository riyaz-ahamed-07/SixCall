from __future__ import annotations

from typing import Any

from app.store.document_store import get_store
from app.tools.wrapper import require_active_session


def list_documents() -> list[dict[str, Any]]:
    """Return document titles and metadata only (no page text). Requires active session.

    When the session is bound to a doc_id, only that document is listed (tenant isolation).
    """
    session = require_active_session()
    store = get_store()

    def _list() -> list[dict[str, Any]]:
        docs = store.list_documents()
        if session.doc_id:
            return [d for d in docs if d.get("doc_id") == session.doc_id]
        return docs

    return session.call("list_documents", _list)
