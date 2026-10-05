from app.db.connection import connect, db_enabled, migrate
from app.store.document_store import get_store

print("db", db_enabled())
migrate()
store = get_store()
n = store.clear_all()
print("cleared", n)
print("remaining_mem", len(store.list_documents()))
with connect() as conn:
    print("db_docs", conn.execute("select count(*) as c from documents").fetchone())
    print("users", conn.execute("select to_regclass('public.users') as t").fetchone())
