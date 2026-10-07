# SixCall API — Fly.io / container deploy
FROM python:3.12-slim-bookworm

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DOC_STORE_DIR=/tmp/sixcall/docs \
    PORT=8000

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY app ./app

# Staging disk (Render free = ephemeral /tmp). Supabase is durable after sync.
RUN mkdir -p /tmp/sixcall/docs /tmp/sixcall/traces

EXPOSE 8000

# Fly sets PORT; default 8000 for local docker runs.
CMD ["sh", "-c", "uvicorn app.server:app --host 0.0.0.0 --port ${PORT:-8000}"]