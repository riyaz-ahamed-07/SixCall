from app.config import DOC_STORE_DIR
from app.db.connection import connect
from app.db.repository import load_all_documents
from app.store.document_store import DocumentStore

with connect() as conn:
    rows = conn.execute(
        "select table_name from information_schema.tables "
        "where table_schema='public' order by 1"
    ).fetchall()
    print("tables", [r["table_name"] for r in rows])

ds = DocumentStore(persist_dir=DOC_STORE_DIR)
print("store_docs", len(ds.list_documents()))
print("sample", ds.list_documents()[:2])
print("db_count", len(load_all_documents()))
