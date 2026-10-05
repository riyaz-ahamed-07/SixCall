from __future__ import annotations

from app.agent.schemas import GetPageArgs
from app.store.document_store import get_store
from app.tools.wrapper import require_active_session


def get_page(doc_id: str, page_number: int) -> str:
    """Return text of exactly one page. Requires active session."""
    GetPageArgs(doc_id=doc_id, page_number=page_number)
    session = require_active_session()
    store = get_store()
    if not isinstance(page_number, int) or isinstance(page_number, bool):
        raise TypeError(f"page_number must be int, got {type(page_number).__name__}")
    return session.call(
        "get_page",
        store.get_page,
        doc_id=doc_id,
        page_number=page_number,
    )
