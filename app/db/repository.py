"""Document + question persistence against Postgres."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.db.connection import connect, db_enabled
from app.store.document_store import DocRecord, Heading

logger = logging.getLogger(__name__)


def delete_document(doc_id: str, *, owner_id: str | None = None) -> bool:
    if not db_enabled() or not doc_id:
        return False
    with connect() as conn:
        # questions.doc_id is not FK-cascaded — remove Q&A + tool traces first.
        if owner_id and owner_id != "local":
            conn.execute(
                """
                DELETE FROM tool_calls
                WHERE question_id IN (
                    SELECT question_id FROM questions
                    WHERE doc_id = %s AND owner_id = %s::uuid
                )
                """,
                (doc_id, owner_id),
            )
            conn.execute(
                "DELETE FROM questions WHERE doc_id = %s AND owner_id = %s::uuid",
                (doc_id, owner_id),
            )
            cur = conn.execute(
                "DELETE FROM documents WHERE doc_id = %s AND owner_id = %s::uuid",
                (doc_id, owner_id),
            )
        else:
            conn.execute(
                """
                DELETE FROM tool_calls
                WHERE question_id IN (
                    SELECT question_id FROM questions WHERE doc_id = %s
                )
                """,
                (doc_id,),
            )
            conn.execute("DELETE FROM questions WHERE doc_id = %s", (doc_id,))
            cur = conn.execute("DELETE FROM documents WHERE doc_id = %s", (doc_id,))
        conn.commit()
        return (cur.rowcount or 0) > 0


def delete_all_documents(*, owner_id: str | None = None) -> int:
    if not db_enabled():
        return 0
    with connect() as conn:
        if owner_id and owner_id != "local":
            conn.execute(
                """
                DELETE FROM tool_calls
                WHERE question_id IN (
                    SELECT question_id FROM questions WHERE owner_id = %s::uuid
                )
                """,
                (owner_id,),
            )
            conn.execute(
                "DELETE FROM questions WHERE owner_id = %s::uuid",
                (owner_id,),
            )
            cur = conn.execute(
                "DELETE FROM documents WHERE owner_id = %s::uuid",
                (owner_id,),
            )
        else:
            conn.execute("DELETE FROM tool_calls")
            conn.execute("DELETE FROM questions")
            cur = conn.execute("DELETE FROM documents")
        conn.commit()
        return int(cur.rowcount or 0)


def save_document(rec: DocRecord) -> None:
    """Persist document + pages + headings to Postgres (source of truth)."""
    if not db_enabled():
        raise RuntimeError("DATABASE_URL is not set; cannot save document to DB")
    from app.db.connection import connect_write
    from psycopg.types.json import Jsonb

    meta = dict(rec.meta or {})
    # Keep precision_index inside meta so DB reloads don't lose dual-index search.
    if rec.precision_index:
        meta["precision_index"] = rec.precision_index
    title = str(meta.get("source_name") or meta.get("title") or rec.doc_id)
    owner_raw = meta.get("owner_id")
    owner_id = str(owner_raw) if owner_raw and str(owner_raw) != "local" else None

    with connect_write() as conn:
        conn.execute(
            """
            INSERT INTO documents (
                doc_id, owner_id, title, source_name, source_path, page_count,
                meta, keyword_index, updated_at
            ) VALUES (
                %(doc_id)s, %(owner_id)s::uuid, %(title)s, %(source_name)s, %(source_path)s,
                %(page_count)s, %(meta)s, %(keyword_index)s, NOW()
            )
            ON CONFLICT (doc_id) DO UPDATE SET
                owner_id = COALESCE(EXCLUDED.owner_id, documents.owner_id),
                title = EXCLUDED.title,
                source_name = EXCLUDED.source_name,
                source_path = EXCLUDED.source_path,
                page_count = EXCLUDED.page_count,
                meta = EXCLUDED.meta,
                keyword_index = EXCLUDED.keyword_index,
                updated_at = NOW()
            """,
            {
                "doc_id": rec.doc_id,
                "owner_id": owner_id,
                "title": title,
                "source_name": meta.get("source_name"),
                "source_path": meta.get("source_path"),
                "page_count": int(meta.get("page_count") or len(rec.pages)),
                "meta": Jsonb(meta),
                "keyword_index": Jsonb(rec.index or {}),
            },
        )
        conn.execute("DELETE FROM pages WHERE doc_id = %s", (rec.doc_id,))
        if rec.pages:
            with conn.cursor() as cur:
                with cur.copy(
                    "COPY pages (doc_id, page_number, body, label) FROM STDIN"
                ) as copy:
                    for page_no, text in sorted(rec.pages.items()):
                        copy.write_row(
                            (
                                rec.doc_id,
                                int(page_no),
                                text or "",
                                str(rec.labels.get(page_no, page_no)),
                            )
                        )
        conn.execute("DELETE FROM headings WHERE doc_id = %s", (rec.doc_id,))
        if rec.headings:
            with conn.cursor() as cur:
                with cur.copy(
                    "COPY headings (doc_id, ord, title, level, start_page, end_page) FROM STDIN"
                ) as copy:
                    for i, h in enumerate(rec.headings):
                        copy.write_row(
                            (
                                rec.doc_id,
                                i,
                                h.title,
                                int(h.level),
                                int(h.start),
                                int(h.end),
                            )
                        )
        conn.commit()
    logger.info(
        "db_save_document doc_id=%s pages=%d headings=%d index_terms=%d",
        rec.doc_id,
        len(rec.pages),
        len(rec.headings),
        len(rec.index or {}),
    )


def load_all_documents(*, owner_id: str | None = None) -> list[DocRecord]:
    if not db_enabled():
        return []
    out: list[DocRecord] = []
    with connect() as conn:
        if owner_id and owner_id != "local":
            docs = conn.execute(
                """
                SELECT doc_id, meta, keyword_index FROM documents
                WHERE owner_id = %s::uuid
                ORDER BY title, doc_id
                """,
                (owner_id,),
            ).fetchall()
        else:
            docs = conn.execute(
                "SELECT doc_id, meta, keyword_index FROM documents ORDER BY title, doc_id"
            ).fetchall()
        for row in docs:
            doc_id = row["doc_id"]
            meta = row["meta"] if isinstance(row["meta"], dict) else json.loads(row["meta"] or "{}")
            index = (
                row["keyword_index"]
                if isinstance(row["keyword_index"], dict)
                else json.loads(row["keyword_index"] or "{}")
            )
            pages_rows = conn.execute(
                "SELECT page_number, body, label FROM pages WHERE doc_id = %s ORDER BY page_number",
                (doc_id,),
            ).fetchall()
            headings_rows = conn.execute(
                """
                SELECT title, level, start_page, end_page
                FROM headings WHERE doc_id = %s ORDER BY ord, id
                """,
                (doc_id,),
            ).fetchall()
            pages = {int(r["page_number"]): r["body"] or "" for r in pages_rows}
            labels = {
                int(r["page_number"]): str(r["label"] or r["page_number"]) for r in pages_rows
            }
            headings = [
                Heading(
                    title=r["title"],
                    level=int(r["level"]),
                    start=int(r["start_page"]),
                    end=int(r["end_page"]),
                )
                for r in headings_rows
            ]
            precision_raw = meta.get("precision_index") if isinstance(meta, dict) else None
            precision_index = (
                {k: list(v) for k, v in precision_raw.items()}
                if isinstance(precision_raw, dict)
                else {}
            )
            out.append(
                DocRecord(
                    doc_id=doc_id,
                    meta=meta,
                    pages=pages,
                    labels=labels,
                    headings=headings,
                    index={k: list(v) for k, v in (index or {}).items()},
                    precision_index=precision_index,
                )
            )
    logger.info("db_load_documents count=%d", len(out))
    return out


def ensure_question(
    question_id: str,
    doc_id: str | None = None,
    question: str = "",
    *,
    owner_id: str | None = None,
) -> None:
    if not db_enabled() or not question_id:
        return
    owner = owner_id if owner_id and owner_id != "local" else None
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO questions (question_id, owner_id, doc_id, question)
            VALUES (%(question_id)s, %(owner_id)s::uuid, %(doc_id)s, %(question)s)
            ON CONFLICT (question_id) DO UPDATE SET
                owner_id = COALESCE(EXCLUDED.owner_id, questions.owner_id),
                doc_id = COALESCE(EXCLUDED.doc_id, questions.doc_id),
                question = CASE
                    WHEN EXCLUDED.question <> '' THEN EXCLUDED.question
                    ELSE questions.question
                END
            """,
            {
                "question_id": question_id,
                "owner_id": owner,
                "doc_id": doc_id,
                "question": question or "",
            },
        )
        conn.commit()


def save_tool_call(record: dict[str, Any], *, owner_id: str | None = None) -> None:
    if not db_enabled():
        return
    qid = str(record.get("question_id") or "")
    if not qid:
        return
    ensure_question(qid, owner_id=owner_id)
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO tool_calls (
                question_id, call_index, tool, args, result_summary, error, ts
            ) VALUES (
                %(question_id)s, %(call_index)s, %(tool)s, %(args)s::jsonb,
                %(result_summary)s, %(error)s, %(ts)s
            )
            ON CONFLICT (question_id, call_index) DO UPDATE SET
                tool = EXCLUDED.tool,
                args = EXCLUDED.args,
                result_summary = EXCLUDED.result_summary,
                error = EXCLUDED.error,
                ts = EXCLUDED.ts
            """,
            {
                "question_id": qid,
                "call_index": int(record.get("call_index") or 0),
                "tool": str(record.get("tool") or ""),
                "args": json.dumps(record.get("args") or {}, ensure_ascii=False),
                "result_summary": str(record.get("result_summary") or ""),
                "error": record.get("error"),
                "ts": float(record.get("timestamp") or 0),
            },
        )
        conn.commit()


def save_tool_calls(records: list[dict[str, Any]], *, owner_id: str | None = None) -> None:
    """Flush completed traces in one connection; local traces survive DB failure."""
    if not db_enabled() or not records:
        return
    owner = owner_id if owner_id and owner_id != "local" else None
    with connect() as conn:
        for qid in dict.fromkeys(str(r.get("question_id") or "") for r in records):
            if qid:
                conn.execute(
                    "INSERT INTO questions (question_id, owner_id) VALUES (%s, %s::uuid) "
                    "ON CONFLICT (question_id) DO NOTHING", (qid, owner),
                )
        rows = [
            (str(r["question_id"]), int(r["call_index"]), str(r["tool"]),
             json.dumps(r.get("args") or {}, ensure_ascii=False),
             str(r.get("result_summary") or ""), r.get("error"), float(r.get("timestamp") or 0))
            for r in records if r.get("question_id")
        ]
        if rows:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO tool_calls (question_id, call_index, tool, args, result_summary, error, ts) "
                    "VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s) "
                    "ON CONFLICT (question_id, call_index) DO UPDATE SET "
                    "tool=EXCLUDED.tool, args=EXCLUDED.args, result_summary=EXCLUDED.result_summary, "
                    "error=EXCLUDED.error, ts=EXCLUDED.ts", rows,
                )
        conn.commit()


def load_tool_trace(
    question_id: str, *, owner_id: str | None = None
) -> list[dict[str, Any]]:
    if not db_enabled() or not question_id:
        return []
    with connect() as conn:
        if owner_id and owner_id != "local":
            owned = conn.execute(
                "SELECT 1 FROM questions WHERE question_id = %s AND owner_id = %s::uuid",
                (question_id, owner_id),
            ).fetchone()
            if not owned:
                return []
        rows = conn.execute(
            """
            SELECT question_id, call_index, tool, args, result_summary, error, ts AS timestamp
            FROM tool_calls
            WHERE question_id = %s
            ORDER BY call_index
            """,
            (question_id,),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        args = row["args"]
        if not isinstance(args, dict):
            try:
                args = json.loads(args or "{}")
            except Exception:
                args = {}
        out.append(
            {
                "question_id": row["question_id"],
                "call_index": row["call_index"],
                "tool": row["tool"],
                "args": args,
                "result_summary": row["result_summary"],
                "error": row["error"],
                "timestamp": row["timestamp"],
            }
        )
    return out


def save_answer(
    *,
    question_id: str,
    doc_id: str,
    question: str,
    answer: dict[str, Any],
    owner_id: str | None = None,
) -> None:
    if not db_enabled() or not question_id:
        return
    owner = owner_id if owner_id and owner_id != "local" else None
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO questions (
                question_id, owner_id, doc_id, question, answer_text, status, calls_used,
                pages_used, quotes, intent, strategy, reason
            ) VALUES (
                %(question_id)s, %(owner_id)s::uuid, %(doc_id)s, %(question)s, %(answer_text)s,
                %(status)s, %(calls_used)s, %(pages_used)s, %(quotes)s::jsonb, %(intent)s,
                %(strategy)s, %(reason)s
            )
            ON CONFLICT (question_id) DO UPDATE SET
                owner_id = COALESCE(EXCLUDED.owner_id, questions.owner_id),
                doc_id = EXCLUDED.doc_id,
                question = EXCLUDED.question,
                answer_text = EXCLUDED.answer_text,
                status = EXCLUDED.status,
                calls_used = EXCLUDED.calls_used,
                pages_used = EXCLUDED.pages_used,
                quotes = EXCLUDED.quotes,
                intent = EXCLUDED.intent,
                strategy = EXCLUDED.strategy,
                reason = EXCLUDED.reason
            """,
            {
                "question_id": question_id,
                "owner_id": owner,
                "doc_id": doc_id,
                "question": question,
                "answer_text": str(answer.get("text") or ""),
                "status": str(answer.get("status") or "insufficient_information"),
                "calls_used": int(answer.get("calls_used") or 0),
                "pages_used": list(answer.get("pages_used") or []),
                "quotes": json.dumps(answer.get("quotes") or [], ensure_ascii=False),
                "intent": answer.get("intent"),
                "strategy": answer.get("strategy"),
                "reason": answer.get("reason"),
            },
        )
        conn.commit()
