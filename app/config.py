from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_KEYS = Path(r"C:\Users\thahs\Documents\RAP_LLM_KEYS.env")


def load_config() -> None:
    local_env = _ROOT / ".env"
    if local_env.exists():
        load_dotenv(local_env, override=True)

    keys_file = os.getenv("APP_KEYS_FILE", "").strip()
    candidates = []
    if keys_file:
        candidates.append(Path(keys_file))
    if _DEFAULT_KEYS.exists():
        candidates.append(_DEFAULT_KEYS)

    for path in candidates:
        if path.exists():
            load_dotenv(path, override=False)
            break

    if not os.getenv("GEMINI_API_KEY") and os.getenv("GOOGLE_API_KEY"):
        os.environ["GEMINI_API_KEY"] = os.environ["GOOGLE_API_KEY"]
    if not os.getenv("GOOGLE_API_KEY") and os.getenv("GEMINI_API_KEY"):
        os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]


load_config()

# Judging hard ceiling is 6; env may only lower it for tests.
_MAX_RAW = int(os.getenv("MAX_TOOL_CALLS", "6"))
MAX_TOOL_CALLS = max(1, min(6, _MAX_RAW))
DOC_STORE_DIR = Path(os.getenv("DOC_STORE_DIR", str(_ROOT / ".data" / "docs")))
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DB_CONNECT_TIMEOUT_SEC = float(os.getenv("DB_CONNECT_TIMEOUT_SEC", "5"))
# Short default for reads / auth; ingest writes override via DB_WRITE_TIMEOUT_MS.
DB_STATEMENT_TIMEOUT_MS = int(os.getenv("DB_STATEMENT_TIMEOUT_MS", "15000"))
# Large PDFs (hundreds of pages + keyword_index) need a long write window.
DB_WRITE_TIMEOUT_MS = int(os.getenv("DB_WRITE_TIMEOUT_MS", "180000"))
# End-to-end ask deadline (planner + tools + one final generation).
REQUEST_DEADLINE_SEC = float(os.getenv("REQUEST_DEADLINE_SEC", "15"))
LLM_ATTEMPT_TIMEOUT_SEC = float(os.getenv("LLM_ATTEMPT_TIMEOUT_SEC", "12"))
# Max provider attempts per complete() call (1 = strict judging).
LLM_MAX_ATTEMPTS = max(1, int(os.getenv("LLM_MAX_ATTEMPTS", "1")))
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
GEMINI_MODEL_LIGHT = os.getenv("GEMINI_MODEL_LIGHT", "gemini-3.5-flash-lite")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_MODEL_FAST = os.getenv("GROQ_MODEL_FAST", "openai/gpt-oss-20b")
# Prefer groq while testing / when Gemini is rate-limited. Values: groq | gemini
LLM_PRIMARY = os.getenv("LLM_PRIMARY", "groq").strip().lower()
# When DATABASE_URL is set, Postgres is the source of truth (local JSON is not a catalog).
SIXCALL_USE_DB = os.getenv("SIXCALL_USE_DB", "auto").strip().lower()
# Disk under DOC_STORE_DIR:
#   staging (default with DB) — write local for fast chat, background Supabase,
#     then delete local JSON/PDF once DB has the catalog (memory keeps serving).
#   1 / keep — leave files on disk forever (local laptop).
#   0 / off — no disk; ingest waits for Supabase (safest on tiny ephemeral disks).
SIXCALL_DISK_CACHE = os.getenv("SIXCALL_DISK_CACHE", "staging").strip().lower()


def cors_allow_origins() -> list[str]:
    """Browser origins allowed to call the API (comma-separated CORS_ORIGINS)."""
    defaults = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://six-call.vercel.app",
    ]
    raw = os.getenv("CORS_ORIGINS", "").strip()
    extras = [part.strip().rstrip("/") for part in raw.split(",") if part.strip()]
    out: list[str] = []
    seen: set[str] = set()
    for origin in defaults + extras:
        key = origin.rstrip("/")
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out


# Vercel preview URLs for this project, e.g. https://six-call-git-main-….vercel.app
CORS_ORIGIN_REGEX = os.getenv(
    "CORS_ORIGIN_REGEX",
    r"https://six-call(-[\w-]+)*\.vercel\.app",
).strip()