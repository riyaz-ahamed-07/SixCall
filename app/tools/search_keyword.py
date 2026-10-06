from __future__ import annotations

from app.agent.schemas import SearchKeywordArgs
from app.store.document_store import get_store
from app.tools.wrapper import require_active_session


def search_keyword(doc_id: str, keyword: str | list[str]) -> list[int]:
    """Return page numbers for one keyword or a ranked pin list. One tool call."""
    SearchKeywordArgs(doc_id=doc_id, keyword=keyword)
    session = require_active_session()
    store = get_store()
    return session.call(
        "search_keyword",
        store.search_keyword,
        doc_id=doc_id,
        keyword=keyword,
    )
