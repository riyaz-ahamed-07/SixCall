"""FastAPI auth dependencies."""

from __future__ import annotations

from typing import Any

from fastapi import Header, HTTPException

from app.db.connection import db_enabled


def bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


def require_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """Require a signed-in user when the database is configured."""
    if not db_enabled():
        # Local/no-DB mode: anonymous operator (tests / offline demo).
        return {"id": "local", "email": "local@sixcall"}

    from app.db import auth as auth_db

    token = bearer_token(authorization)
    user = auth_db.user_from_token(token or "")
    if not user:
        raise HTTPException(status_code=401, detail="Sign in required")
    return user


def optional_user(authorization: str | None = Header(default=None)) -> dict[str, Any] | None:
    if not db_enabled():
        return {"id": "local", "email": "local@sixcall"}
    from app.db import auth as auth_db

    token = bearer_token(authorization)
    return auth_db.user_from_token(token or "")
