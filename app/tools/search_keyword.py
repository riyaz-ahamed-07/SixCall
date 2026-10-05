from __future__ import annotations

from app.store.document_store import get_store
from app.tools.wrapper import require_active_session


def search_keyword(doc_id: str, keyword: str) -> list[int]:
    """Return page numbers only for a keyword/phrase match. Requires active session."""
    session = require_active_session()
    store = get_store()
    return session.call(
        "search_keyword",
        store.search_keyword,
        doc_id=doc_id,
        keyword=keyword,
    )
