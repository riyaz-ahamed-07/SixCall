"""Lightweight email/password auth against Postgres (demo-grade)."""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from app.db.connection import connect, db_enabled

logger = logging.getLogger(__name__)

_SESSION_DAYS = 14
_PBKDF2_ITERS = 120_000
# Avoid a remote round-trip on every /ask /ingest while testing locally.
_TOKEN_CACHE_TTL_SEC = 300.0
_TOKEN_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_TOKEN_CACHE_LOCK = threading.Lock()


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ITERS
    )
    return f"pbkdf2_sha256${_PBKDF2_ITERS}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        algo, iters_s, salt_hex, digest_hex = encoded.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iters_s),
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


def signup(email: str, password: str) -> dict[str, Any]:
    if not db_enabled():
        raise RuntimeError("DATABASE_URL is not configured")
    email_n = email.strip().lower()
    if "@" not in email_n or len(email_n) < 5:
        raise ValueError("Enter a valid email")
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters")

    password_hash = _hash_password(password)
    with connect() as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE email = %s", (email_n,)
        ).fetchone()
        if existing:
            raise ValueError("An account with this email already exists")
        row = conn.execute(
            """
            INSERT INTO users (email, password_hash)
            VALUES (%s, %s)
            RETURNING id, email, created_at
            """,
            (email_n, password_hash),
        ).fetchone()
        token, expires = _create_session(conn, str(row["id"]))
        conn.commit()
    user = {"id": str(row["id"]), "email": row["email"]}
    _cache_session(token, user)
    logger.info("auth_signup email=%s", email_n)
    return {
        "token": token,
        "expires_at": expires.isoformat(),
        "user": user,
    }


def login(email: str, password: str) -> dict[str, Any]:
    if not db_enabled():
        raise RuntimeError("DATABASE_URL is not configured")
    email_n = email.strip().lower()
    with connect() as conn:
        row = conn.execute(
            "SELECT id, email, password_hash FROM users WHERE email = %s",
            (email_n,),
        ).fetchone()
        if not row or not _verify_password(password, row["password_hash"]):
            raise ValueError("Invalid email or password")
        token, expires = _create_session(conn, str(row["id"]))
        conn.commit()
    user = {"id": str(row["id"]), "email": row["email"]}
    _cache_session(token, user)
    logger.info("auth_login email=%s", email_n)
    return {
        "token": token,
        "expires_at": expires.isoformat(),
        "user": user,
    }


def logout(token: str) -> None:
    if not db_enabled() or not token:
        return
    with _TOKEN_CACHE_LOCK:
        _TOKEN_CACHE.pop(token, None)
    with connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token = %s", (token,))
        conn.commit()


def user_from_token(token: str) -> dict[str, Any] | None:
    if not db_enabled() or not token:
        return None
    now = time.time()
    with _TOKEN_CACHE_LOCK:
        hit = _TOKEN_CACHE.get(token)
        if hit is not None and hit[0] > now:
            return dict(hit[1])

    with connect() as conn:
        row = conn.execute(
            """
            SELECT u.id, u.email, s.expires_at
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token = %s
            """,
            (token,),
        ).fetchone()
        if not row:
            with _TOKEN_CACHE_LOCK:
                _TOKEN_CACHE.pop(token, None)
            return None
        expires = row["expires_at"]
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires < datetime.now(timezone.utc):
            conn.execute("DELETE FROM sessions WHERE token = %s", (token,))
            conn.commit()
            with _TOKEN_CACHE_LOCK:
                _TOKEN_CACHE.pop(token, None)
            return None
    user = {"id": str(row["id"]), "email": row["email"]}
    with _TOKEN_CACHE_LOCK:
        _TOKEN_CACHE[token] = (now + _TOKEN_CACHE_TTL_SEC, user)
    return user


def _cache_session(token: str, user: dict[str, Any]) -> None:
    with _TOKEN_CACHE_LOCK:
        _TOKEN_CACHE[token] = (time.time() + _TOKEN_CACHE_TTL_SEC, dict(user))


def _create_session(conn: Any, user_id: str) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=_SESSION_DAYS)
    conn.execute(
        """
        INSERT INTO sessions (token, user_id, expires_at)
        VALUES (%s, %s::uuid, %s)
        """,
        (token, user_id, expires),
    )
    return token, expires
