# SixCall — one-page design memo

**Budgeted document Q&A.** SixCall answers questions over an ingested PDF using four tools (`list_documents`, `list_headings`, `search_keyword`, `get_page`) and a hard ceiling of **six tool calls** per question. There is no agent framework. The happy path is one answer generation after a local section walk.

## Architecture

1. **Ingest** — pymupdf4llm writes page text as markdown (headings and tables). The layout network stays off: that is the fast path versus plain pypdfium2 text or a heavy marker-pdf model. PyMuPDF still builds the section tree (TOC, then font size, then lexical heading lines) and OCRs a page when the markdown is empty. `search_keyword` keeps two lexical maps internally: precision (unstemmed numbers, CapWords, exact phrases) and recall (stemmed tokens). `doc_id` is `sha256(owner:bytes)[:16]`.
2. **Route** — New questions always use tools. `SIXCALL_FOLLOWUPS` defaults off; a result with zero tool calls is sent back through the agent. Overview asks still sample pages through `get_page`.
3. **Agent** — Pins are copied from the question (numbers, CapWords, quotes, clause ids). Heading titles are matched locally, at most three ranges. `search_keyword` returns page numbers only: precision first, stemmed recall only when precision names nothing. Overlap that is already strong makes no planner call (`planner_llm=0`). A weak outline may spend one TOC pick that can only return existing titles and terms already in the question. One answer call cites span ids built after `get_page`. When a later statement can supersede an earlier one, the newest keyword hit stays in the pages that are read.
4. **Fail closed** — Spans are built only from pages `get_page` already returned (sentences, table rows, or code lines). Unknown span ids, swapped numbers, and dropped negations are rejected in pure Python. A plan, draft, or ask result that does not match its shape is refused. Empty evidence becomes `insufficient information`.

## Why this shape

| Constraint | Choice                                                                                |
| ---------- | ------------------------------------------------------------------------------------- |
| 6 calls    | Headings + at most two question pins, then `get_page`; one call held for repair      |
| Navigation | Section tree + question pins + 6-call ledger + fail-closed span ids                  |
| Grounding  | Span id must exist; exact or high string match with number and negation guards       |
| Multi-user | Auth bearer + `owner_id` on documents/questions; clear-all is owner-scoped            |
| Migrations | Explicit `python -m app.cli migrate` against Supabase **dev** — not silent on startup |

## Limits (honest)

- Overview samples pages; long docs are not fully read (coverage is disclosed).
- Quote existence ≠ full entailment of every sentence; prefer validated evidence IDs in future.
- Chat UI restores sessionStorage history; durable conversation threads are not modeled yet.
- Accuracy on unseen PDFs must be rehearsed live (contradictions, absent answers, prompt injection).

## Ops

```bash
# Point DATABASE_URL at Supabase *dev*, then:
python -m app.cli migrate
uvicorn app.server:app --port 8000
cd web && npm run dev
```

Submit with: upload → question → cited answer → `/trace/{question_id}` export.
