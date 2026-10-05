"""HTTP API for the SixCall web UI."""

from __future__ import annotations

import logging
import re
import tempfile
import time
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from app.api import ask, get_trace, ingest_pdf, list_docs, overview
from app.db.connection import db_enabled
from app.deps import bearer_token, require_user
from app.store.document_store import PageNotFoundError, get_store

logger = logging.getLogger(__name__)

app = FastAPI(title="SixCall", version="0.1.0")


@app.middleware("http")
async def request_timing(request: Request, call_next):
    started = time.perf_counter()
    try:
        response = await call_next(request)
        response.headers["Server-Timing"] = f"total;dur={(time.perf_counter() - started) * 1000:.1f}"
        return response
    finally:
        logger.info("request_timing method=%s path=%s elapsed_ms=%.1f",
                    request.method, request.url.path, (time.perf_counter() - started) * 1000)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_DOC_ID_RE = re.compile(r"^[a-f0-9]{16}$")
_MAX_QUESTION_CHARS = 2000
_MAX_UPLOAD_BYTES = 25 * 1024 * 1024

UserDep = Annotated[dict[str, Any], Depends(require_user)]


class AskRequest(BaseModel):
    doc_id: str = Field(min_length=16, max_length=16)
    question: str = Field(min_length=1, max_length=_MAX_QUESTION_CHARS)
    history: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("doc_id")
    @classmethod
    def _doc_id_shape(cls, value: str) -> str:
        v = (value or "").strip().lower()
        if not _DOC_ID_RE.fullmatch(v):
            raise ValueError("doc_id must be a 16-char hex ingest id")
        return v

    @field_validator("question")
    @classmethod
    def _question_nonblank(cls, value: str) -> str:
        q = (value or "").strip()
        if not q:
            raise ValueError("question must not be blank")
        return q

    @field_validator("history")
    @classmethod
    def _history_bounded(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for item in (value or [])[-12:]:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip().lower()
            if role not in {"user", "assistant"}:
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            entry: dict[str, Any] = {"role": role, "text": text[:4000]}
            quotes = item.get("quotes")
            if isinstance(quotes, list):
                entry["quotes"] = quotes[:6]
            status = str(item.get("status") or "").strip().lower()
            if status in {"ok", "insufficient_information"}:
                entry["status"] = status
            out.append(entry)
        return out


class AuthBody(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=6, max_length=128)


def _owner_id(user: dict[str, Any]) -> str:
    return str(user.get("id") or "local")


def _require_owned_doc(doc_id: str, owner_id: str) -> None:
    store = get_store()
    if store.get(doc_id) is None:
        raise HTTPException(status_code=404, detail="Unknown doc_id")
    if not store.owned_by(doc_id, owner_id):
        raise HTTPException(status_code=404, detail="Unknown doc_id")


@app.get("/health")
def health() -> dict[str, Any]:
    store = get_store()
    return {
        "status": "ok",
        "db": db_enabled(),
        "documents": len(store.list_documents()),
    }


@app.get("/documents")
def documents(user: UserDep) -> list[dict[str, Any]]:
    return list_docs(owner_id=_owner_id(user))


@app.get("/documents/{doc_id}/file")
def document_file(doc_id: str, user: UserDep) -> FileResponse:
    """Stream the original uploaded PDF for in-app preview."""
    v = (doc_id or "").strip().lower()
    if not _DOC_ID_RE.fullmatch(v):
        raise HTTPException(status_code=400, detail="Invalid doc_id")
    owner = _owner_id(user)
    _require_owned_doc(v, owner)
    path = get_store().pdf_file_path(v)
    if path is None:
        raise HTTPException(
            status_code=404,
            detail="Original PDF not stored — re-upload the file to enable preview",
        )
    filename = "document.pdf"
    rec = get_store().get(v)
    if rec is not None:
        filename = str(rec.meta.get("source_name") or filename)
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=filename,
        content_disposition_type="inline",
    )


@app.get("/documents/{doc_id}/preview")
def document_preview(
    doc_id: str,
    user: UserDep,
    page: int = 1,
) -> dict[str, Any]:
    """Text preview of an owned document for the UI modal (not a budgeted tool)."""
    v = (doc_id or "").strip().lower()
    if not _DOC_ID_RE.fullmatch(v):
        raise HTTPException(status_code=400, detail="Invalid doc_id")
    owner = _owner_id(user)
    _require_owned_doc(v, owner)
    if page < 1:
        raise HTTPException(status_code=400, detail="page must be >= 1")
    try:
        return get_store().preview(v, page_number=page)
    except PageNotFoundError:
        raise HTTPException(status_code=404, detail="Page not found") from None
    except Exception:
        raise HTTPException(status_code=500, detail="Preview failed") from None


@app.delete("/documents/{doc_id}")
def delete_one_document(doc_id: str, user: UserDep) -> dict[str, Any]:
    v = (doc_id or "").strip().lower()
    if not _DOC_ID_RE.fullmatch(v):
        raise HTTPException(status_code=400, detail="Invalid doc_id")
    ok = get_store().delete_document(v, owner_id=_owner_id(user))
    if not ok:
        raise HTTPException(status_code=404, detail="Unknown doc_id")
    return {"deleted": v}


@app.delete("/documents")
def delete_all_documents(user: UserDep) -> dict[str, Any]:
    """Wipe the current user's documents only (never other tenants)."""
    n = get_store().clear_all(owner_id=_owner_id(user))
    return {"deleted": n}


@app.post("/ingest")
def ingest(user: UserDep, file: UploadFile = File(...)) -> dict[str, str]:
    """Sync route: PDF parse/OCR is CPU-bound; avoid blocking the async event loop."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF uploads are supported")

    raw = file.file.read(_MAX_UPLOAD_BYTES + 1)
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="PDF exceeds 25MB limit")
    if not raw.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="File does not look like a PDF")

    display_name = Path(file.filename).name[:180]
    suffix = Path(display_name).suffix or ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(raw)
        tmp_path = tmp.name

    try:
        try:
            doc_id = ingest_pdf(tmp_path, owner_id=_owner_id(user), source_name=display_name)
        except Exception as exc:
            logger.exception("ingest_failed error=%s", type(exc).__name__)
            raise HTTPException(
                status_code=500, detail=f"Ingest failed: {type(exc).__name__}"
            ) from None
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return {"doc_id": doc_id, "filename": display_name}


@app.post("/ask")
def ask_question(body: AskRequest, user: UserDep) -> dict[str, Any]:
    owner = _owner_id(user)
    _require_owned_doc(body.doc_id, owner)
    try:
        answer = ask(
            body.doc_id,
            body.question,
            history=body.history,
            owner_id=owner,
        )
    except Exception:
        raise HTTPException(status_code=500, detail="Agent failed") from None
    return answer.model_dump()


class OverviewRequest(BaseModel):
    doc_id: str = Field(min_length=16, max_length=16)
    question: str | None = Field(default=None, max_length=_MAX_QUESTION_CHARS)
    light: bool = False

    @field_validator("doc_id")
    @classmethod
    def _doc_id_shape(cls, value: str) -> str:
        v = (value or "").strip().lower()
        if not _DOC_ID_RE.fullmatch(v):
            raise ValueError("doc_id must be a 16-char hex ingest id")
        return v

    @field_validator("question")
    @classmethod
    def _question_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        q = value.strip()
        return q or None


@app.post("/overview")
def overview_document(body: OverviewRequest, user: UserDep) -> dict[str, Any]:
    """Document overview. light=True uses headings only (post-ingest orientation)."""
    owner = _owner_id(user)
    _require_owned_doc(body.doc_id, owner)
    try:
        answer = overview(
            body.doc_id,
            body.question,
            owner_id=owner,
            light=bool(body.light),
        )
    except Exception:
        raise HTTPException(status_code=500, detail="Overview failed") from None
    return answer.model_dump()


@app.get("/trace/{question_id}")
def trace(question_id: str, user: UserDep) -> list[dict[str, Any]]:
    safe = "".join(c for c in question_id if c.isalnum() or c in "-_")[:64]
    if not safe:
        raise HTTPException(status_code=400, detail="Invalid question_id")
    return get_trace(safe, owner_id=_owner_id(user))


@app.post("/auth/signup")
def auth_signup(body: AuthBody) -> dict[str, Any]:
    if not db_enabled():
        raise HTTPException(status_code=503, detail="Database is not configured")
    from app.db import auth as auth_db

    try:
        return auth_db.signup(body.email, body.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except Exception as exc:
        logger.exception("signup_failed")
        raise HTTPException(
            status_code=500, detail=f"Signup failed: {type(exc).__name__}"
        ) from None


@app.post("/auth/login")
def auth_login(body: AuthBody) -> dict[str, Any]:
    if not db_enabled():
        raise HTTPException(status_code=503, detail="Database is not configured")
    from app.db import auth as auth_db

    try:
        return auth_db.login(body.email, body.password)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from None
    except Exception as exc:
        logger.exception("login_failed")
        raise HTTPException(
            status_code=500, detail=f"Login failed: {type(exc).__name__}"
        ) from None


@app.post("/auth/logout")
def auth_logout(authorization: str | None = Header(default=None)) -> dict[str, str]:
    from app.db import auth as auth_db

    token = bearer_token(authorization)
    auth_db.logout(token or "")
    return {"status": "ok"}


@app.get("/auth/me")
def auth_me(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    if not db_enabled():
        raise HTTPException(status_code=503, detail="Database is not configured")
    from app.db import auth as auth_db

    token = bearer_token(authorization)
    user = auth_db.user_from_token(token or "")
    if not user:
        raise HTTPException(status_code=401, detail="Not signed in")
    return {"user": user}
