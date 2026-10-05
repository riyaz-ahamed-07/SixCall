"""Apply SixCall schema to Supabase/Postgres."""

from __future__ import annotations

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS sessions_user_id_idx ON sessions(user_id);
CREATE INDEX IF NOT EXISTS sessions_expires_at_idx ON sessions(expires_at);

CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY,
    owner_id UUID REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT '',
    source_name TEXT,
    source_path TEXT,
    page_count INTEGER NOT NULL DEFAULT 0,
    meta JSONB NOT NULL DEFAULT '{}'::jsonb,
    keyword_index JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE documents ADD COLUMN IF NOT EXISTS owner_id UUID REFERENCES users(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS documents_owner_id_idx ON documents(owner_id);

CREATE TABLE IF NOT EXISTS pages (
    doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL CHECK (page_number >= 1),
    body TEXT NOT NULL DEFAULT '',
    label TEXT,
    PRIMARY KEY (doc_id, page_number)
);

CREATE TABLE IF NOT EXISTS headings (
    id BIGSERIAL PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    ord INTEGER NOT NULL DEFAULT 0,
    title TEXT NOT NULL,
    level INTEGER NOT NULL DEFAULT 1,
    start_page INTEGER NOT NULL,
    end_page INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS headings_doc_id_idx ON headings(doc_id);

CREATE TABLE IF NOT EXISTS questions (
    question_id TEXT PRIMARY KEY,
    owner_id UUID REFERENCES users(id) ON DELETE CASCADE,
    doc_id TEXT,
    question TEXT NOT NULL DEFAULT '',
    answer_text TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'insufficient_information',
    calls_used INTEGER NOT NULL DEFAULT 0,
    pages_used INTEGER[] NOT NULL DEFAULT '{}',
    quotes JSONB NOT NULL DEFAULT '[]'::jsonb,
    intent TEXT,
    strategy TEXT,
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE questions ADD COLUMN IF NOT EXISTS owner_id UUID REFERENCES users(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS questions_doc_id_idx ON questions(doc_id);
CREATE INDEX IF NOT EXISTS questions_owner_id_idx ON questions(owner_id);

CREATE TABLE IF NOT EXISTS tool_calls (
    id BIGSERIAL PRIMARY KEY,
    question_id TEXT NOT NULL REFERENCES questions(question_id) ON DELETE CASCADE,
    call_index INTEGER NOT NULL,
    tool TEXT NOT NULL,
    args JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_summary TEXT NOT NULL DEFAULT '',
    error TEXT,
    ts DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM NOW()),
    UNIQUE (question_id, call_index)
);

CREATE INDEX IF NOT EXISTS tool_calls_question_id_idx ON tool_calls(question_id);
"""
