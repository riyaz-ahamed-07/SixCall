# SixCall — Budgeted Document-Answering Agent

Hackathon build: a **budgeted PDF Q&A agent** with a FastAPI backend and a Next.js demo UI.

Upload a PDF, ask questions from the Python API, CLI, or browser. Answers are constrained by **4 document tools** and a hard **6 tool-call budget**. The agent may **abstain** when quotes cannot be verified.

---

## Table of contents

1. [System overview](#system-overview)
2. [Technology stack](#technology-stack)
3. [Layered architecture](#layered-architecture)
4. [Agent loop](#agent-loop)
5. [Document ingest](#document-ingest)
6. [Tool / store boundary](#tool--store-boundary)
7. [Web UI](#web-ui)
8. [Auth & database](#auth--database)
9. [LLM routing](#llm-routing)
10. [Setup](#setup)
11. [API / CLI](#api--cli)
12. [Tests & failure modes](#tests--failure-modes)

---

## System overview

End-to-end path from browser → API → agent → tools → store → LLM → verified answer.

```mermaid
flowchart LR
  subgraph Client["Web client"]
    UI["Next.js 16 + React 19<br/>AgentShell"]
  end

  subgraph API["Backend API"]
    FA["FastAPI + Uvicorn"]
    AUTH["Bearer auth"]
    AGENT["Agent loop"]
    TOOLS["4 tools + budget wrapper"]
    STORE["DocumentStore"]
    LLM["LiteLLM client"]
  end

  subgraph Data["Persistence"]
    DISK["Local .data/ cache"]
    PG["Supabase Postgres"]
  end

  subgraph Models["LLM providers"]
    GROQ["Groq"]
    GEM["Gemini"]
  end

  UI -->|HTTP /ingest /ask /documents| FA
  FA --> AUTH --> AGENT
  AGENT --> TOOLS --> STORE
  AGENT --> LLM
  STORE --> DISK
  STORE --> PG
  LLM --> GROQ
  LLM --> GEM
```

---

## Technology stack

| Area            | Technology                                       | Role in SixCall                          |
| --------------- | ------------------------------------------------ | ---------------------------------------- |
| **Web UI**      | Next.js 16, React 19, TypeScript, Tailwind CSS 4 | Chat shell, auth pages, upload / ask UX  |
| **API**         | FastAPI, Uvicorn, python-multipart               | REST: ingest, ask, documents, auth       |
| **Validation**  | Pydantic v2                                      | Request/response models                  |
| **Config**      | python-dotenv                                    | `.env` + optional private keys file      |
| **PDF parse**   | pymupdf4llm + PyMuPDF                            | Markdown page text; TOC/font headings; OCR fallback |
| **Search**      | Precision phrases + stemmed recall, inside `search_keyword` | Page numbers only                 |
| **NLP helpers** | NLTK (bundled `app/nltk_data`)                   | Planner tokenization / stopwords         |
| **Quote check** | Exact span after Unicode/whitespace norm         | Verifier rejects paraphrased quotes      |
| **LLM gateway** | LiteLLM                                          | Groq / Gemini with primary + fallback    |
| **Database**    | Supabase Postgres via `psycopg`                  | Docs, users, sessions, Q&A, traces       |
| **Local cache** | `.data/docs`, `.data/traces`                     | Fast local store; dual-write when DB set |
| **Tests**       | pytest                                           | Budget, verifier, store isolation, NLP   |

**Explicitly not used:** agent frameworks (LangChain, LangGraph, LlamaIndex) and external outline APIs. Page selection is the section tree plus the four tools.

```mermaid
mindmap
  root((SixCall))
    Frontend
      Next.js 16
      React 19
      TypeScript
      Tailwind CSS 4
    Backend
      FastAPI
      Uvicorn
      Pydantic
      python-dotenv
    Document layer
      PyMuPDF
      Snowball stemmer
      NLTK
      Inverted index
    Intelligence
      LiteLLM
      Groq
      Gemini
      Quote verifier
    Data
      Supabase Postgres
      psycopg
      Local .data cache
```

---

## Layered architecture

Two layers, enforced in code. The agent package imports **only the four tool functions** (+ wrapper helpers). It must **not** import `app.store` (see `tests/test_no_store_leak.py`).

| Layer                                       | Owns                                                    | Sees                                             |
| ------------------------------------------- | ------------------------------------------------------- | ------------------------------------------------ |
| **Tool / store** (`app/store`, `app/tools`) | Parsed pages, headings, keyword index                   | Full document data                               |
| **Agent** (`app/agent`)                     | Planner → search → score → `get_page` → answer → verify | Only tool return values for the current question |

```mermaid
flowchart TB
  subgraph AgentLayer["Agent layer — app/agent"]
    PLAN["planner.py<br/>LLM plan + keywords"]
    LOOP["loop.py<br/>orchestrator"]
    SCORE["scorer.py<br/>classic IDF + headings"]
    ANS["answerer.py<br/>LLM answer + evidence IDs"]
    VER["verifier.py<br/>exact quote spans"]
    FU["followup.py<br/>history reuse"]
  end

  subgraph ToolLayer["Tool layer — app/tools"]
    W["wrapper.py<br/>budget ≤ 6 · audit log"]
    T1["list_documents"]
    T2["list_headings"]
    T3["search_keyword"]
    T4["get_page"]
  end

  subgraph StoreLayer["Store — app/store"]
    DS["DocumentStore<br/>pages · headings · index"]
  end

  LOOP --> PLAN
  LOOP --> SCORE
  LOOP --> ANS --> VER
  LOOP --> FU
  LOOP --> W
  W --> T1 & T2 & T3 & T4
  T1 & T2 & T3 & T4 --> DS

  AgentLayer -.->|forbidden import| StoreLayer
```

### The only 4 tools

1. `list_documents()` — titles + metadata
2. `list_headings(doc_id)` — TOC / headings
3. `get_page(doc_id, page_number)` — text of **exactly one** page
4. `search_keyword(doc_id, keyword)` — **page numbers only**

`app/tools/wrapper.py` logs every call and **refuses a 7th** tool call for that `question_id`, forcing decline / insufficient information.

### What is unique here

The ceiling is a **budget ledger** (six calls, logged, seventh refused). Navigation is a **section tree** from `list_headings`, **question-only pins** (a search term must appear in the question), a **supersede lock** that keeps the latest keyword hit page, and **fail-closed evidence ids** checked without another model call. `search_keyword` still returns page numbers only.

---

## Agent loop

Happy path: **no planner model call**. One answer call after the tools. A weak outline may spend one TOC pick, and only to choose existing heading titles plus terms already in the question. A failed draft may spend one held `get_page` and one more answer. New questions do not answer with zero tools (`SIXCALL_FOLLOWUPS` defaults off).

```mermaid
sequenceDiagram
  participant U as User / CLI
  participant A as Agent loop
  participant T as Tools (≤6)
  participant Ans as Answer LLM
  participant V as Span verifier

  U->>A: ask(doc_id, question)
  A->>T: list_headings
  Note over A: pins copied from the question<br/>heading-title overlap
  A->>T: search_keyword (precision, else recall)
  T-->>A: page numbers
  A->>T: get_page (reserve one repair slot)
  T-->>A: page text
  Note over A: spans built here, with stable ids
  A->>Ans: one answer, cite span ids
  A->>V: id exists, numbers and negations agree
  alt verified
    A-->>U: status=ok
  else repair budget remains
    A->>T: one more get_page
    A->>Ans: one more answer
  else no evidence
    A-->>U: insufficient information
  end
```

**Budget:** `1×list_headings + ≤2×search_keyword + ≤3–4×get_page ≤ 6`.

Page text is **untrusted data**. Injection-like lines are flagged; the answer follows the user question.

---

## Document ingest

```mermaid
flowchart LR
  PDF["PDF upload"] --> TMP["Temp file"]
  TMP --> PYM["pymupdf4llm page text<br/>PyMuPDF TOC + OCR fallback"]
  PYM --> CLEAN["clean_page_text<br/>TOC strip · dehyphen"]
  CLEAN --> HEAD["Section tree<br/>TOC, fonts, lexical"]
  CLEAN --> IDX["Dual lexical index<br/>precision then recall"]
  HEAD --> REC["DocRecord"]
  IDX --> REC
  REC --> DISK[".data/docs/*.json"]
  REC --> PG["Postgres documents"]
  REC --> ID["doc_id = sha256[:16]<br/>(owner-scoped when auth)"]
```

- Display name = **uploaded filename** (not temp path stem).
- Same bytes (+ owner) → same `doc_id` (idempotent ingest).
- OCR path triggers on near-empty / high-garbage pages when available.

---

## Tool / store boundary

```mermaid
flowchart TB
  Q["question_id session"] --> W["Budget wrapper<br/>MAX_TOOL_CALLS = 6"]
  W -->|call 1–6| STORE["DocumentStore"]
  W -->|call 7+| BLOCK["BudgetExceededError<br/>→ abstain"]
  W --> TRACE["Tool trace JSON<br/>.data/traces + Postgres"]
```

| Tool             | Returns                 | Burns budget                  |
| ---------------- | ----------------------- | ----------------------------- |
| `list_documents` | Doc metadata list       | Yes                           |
| `list_headings`  | Heading tree / ranges   | Yes                           |
| `search_keyword` | `list[int]` page hits   | Yes (aliases inside one call) |
| `get_page`       | One page’s cleaned text | Yes                           |

---

## Web UI

```mermaid
flowchart TB
  subgraph Pages["Next.js App Router"]
    LAND["/ landing"]
    LOGIN["/login · /signup"]
    APP["/app AgentShell"]
    DOCS["/docs"]
  end

  subgraph Shell["AgentShell"]
    SIDE["SidebarNav<br/>docs · upload · new chat"]
    CHAT["Turns · ThinkingState · ToolChips"]
    PROMPT["PromptBar"]
    UP["UploadProgress"]
  end

  APP --> SIDE & CHAT & PROMPT & UP
  CHAT -->|Bearer token| API["FastAPI :8000"]
  UP -->|POST /ingest| API
  PROMPT -->|POST /ask| API
```

Run separately from the API (UI talks to `http://127.0.0.1:8000` directly so long `/ask` requests are not killed by a Next rewrite proxy).

---

## Auth & database

```mermaid
flowchart LR
  UI["Browser"] -->|email/password| AUTH["/auth/signup · /auth/login"]
  AUTH --> USERS["Postgres users"]
  AUTH -->|JWT / session token| UI
  UI -->|Authorization: Bearer| API["Protected routes"]
  API --> OWN["Owner-scoped docs & questions"]
  OWN --> PG["Supabase Postgres"]
  OWN --> LOCAL[".data dual-write cache"]
```

- Set `DATABASE_URL` (Session pooler, `sslmode=require`, percent-encode passwords).
- Apply schema **explicitly**: `python -m app.cli migrate` (API startup does **not** migrate).
- Prefer **dev** branch for writes — never auto-migrate production/`main`.
- `DELETE /documents` clears only the signed-in user’s files when auth is on.

---

## LLM routing

```mermaid
flowchart LR
  REQ["complete_json / complete"] --> PRIM{"LLM_PRIMARY"}
  PRIM -->|groq| G1["Groq main / fast"]
  PRIM -->|gemini| M1["Gemini main / light"]
  G1 -->|fallback| M1
  M1 -->|fallback| G1
  G1 & M1 --> OUT["JSON plan or answer"]
```

- Planner uses the **light** model path; answer uses the **main** path.
- Attempt timeouts and a request deadline (`REQUEST_DEADLINE_SEC`) bound long asks.
- Total provider failure → `insufficient_information`.

---

## Setup

```bash
cd C:\Users\thahs\Projects\SixCall
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

Keys: copy `.env.example` → `.env`, or keep using your private file  
`C:\Users\thahs\Documents\RAP_LLM_KEYS.env` (auto-loaded when present).

**Never commit API keys.**

### Web UI + API

```bash
# terminal 1 — API (prefer no --reload during demos; reload can kill in-flight /ask)
.\.venv\Scripts\activate
uvicorn app.server:app --port 8000

# terminal 2 — UI
cd web
npm install
npm run dev
```

Open http://localhost:3000 — sign up / log in when `DATABASE_URL` is set, upload a PDF, ask questions.

### Database

```bash
python -m app.cli migrate
```

---

## API / CLI

### Python API

```python
from app import ingest_pdf, ask, list_docs, get_trace

doc_id = ingest_pdf("policy.pdf")
answer = ask(doc_id, "What is the refund window?")
print(answer.status, answer.text, answer.calls_used)
print(get_trace(answer.question_id))
```

`Answer`: `{text, status, pages_used, tool_trace, calls_used, question_id, quotes, ...}`  
`status` is `ok` or `insufficient_information`.

### CLI

```bash
# Local JSON only (no database required for the demo)
SIXCALL_USE_DB=0 python -m app.cli ingest path/to/file.pdf
SIXCALL_USE_DB=0 python -m app.cli ask <doc_id> "What is the refund window?"
python -m app.cli trace <question_id>
python -m app.cli docs
```

The ask view prints tool milliseconds and answer-model milliseconds separately. `python -m pytest -q` runs the suite, including the multi-page, supersede, absent, injection, repair, and zero-tool cases.

### HTTP (selected)

| Method   | Path                          | Purpose                                    |
| -------- | ----------------------------- | ------------------------------------------ |
| `POST`   | `/auth/signup`, `/auth/login` | Account + token                            |
| `POST`   | `/ingest`                     | Upload PDF                                 |
| `GET`    | `/documents`                  | List owned docs                            |
| `DELETE` | `/documents/{doc_id}`         | Delete one doc                             |
| `POST`   | `/ask`                        | Ask (optional chat history for follow-ups) |
| `GET`    | `/health`                     | Liveness + DB flag                         |

---

## Tests & failure modes

```bash
pytest -q
```

Covered: 7th call blocked · `search_keyword` returns ints · agent does not import store · fabricated quotes rejected · empty search → insufficient information · stable `doc_id` for same bytes · follow-ups · query NLP.

### Hardened (common silent misses)

- Unicode / PDF asterisks (`A∗` vs `A*`), ligatures (`ﬁ`), soft hyphens, NBSP, fancy dashes
- Tech tokens: `A*`, `C++`, `C#`, `O(n…)`
- Keyword aliases expanded _inside_ `search_keyword` (no extra tool-call budget)
- OCR also triggered on CID/`U+FFFD` garbage pages
- Extract flags dissolve ligatures + dehyphenate; inline TOC strip before hyphen joins

### Still possible

- **True synonym miss**: PDF says “termination”, query says “halting”
- **Weak structure**: no TOC + uniform fonts → thin heading hints
- **OCR gaps**: Tesseract missing or bad scans
- **Budget**: multi-hop needing many pages under a 6-call cap → abstain
- **LLM outage**: Gemini↔Groq fallback; total failure → insufficient information

### Dependencies

```
pymupdf, pymupdf4llm, litellm, python-dotenv, pydantic, rapidfuzz, snowballstemmer,
nltk, pytest, fastapi, uvicorn, python-multipart, psycopg
```

Query planning uses NLTK `word_tokenize(..., preserve_line=True)` and English stopwords from bundled `app/nltk_data` (no runtime downloads). Technical tokens and meaning-changing words (`not`, `before`, `after`) are preserved. Include `app/nltk_data` when packaging.
