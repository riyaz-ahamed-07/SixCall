# SixCall — one-page design memo

**Budgeted document Q&A without RAG.** SixCall answers questions over an ingested PDF using four tools (`list_documents`, `list_headings`, `search_keyword`, `get_page`) and a hard ceiling of **six tool calls** per question. There is no vector index, no agent framework, and **one** final LLM generation after retrieval.

## Architecture

1. **Ingest** — PyMuPDF extracts immutable page text, TOC/font headings, and a stemmed inverted index. `doc_id` is `sha256(owner:bytes)[:16]` so tenants isolate identical files.
2. **Route** — Follow-ups reuse prior chat (0 tools). Whole-document overview asks (`What is this document about?`) sample ≤5 pages via headings (or even sampling when there is no TOC). Everything else runs the tree∩keyword agent.
3. **Agent** — Planner proposes keywords/heading hints; tools run under a `ContextVar` budget; pages are fetched affordably; quotes must match page text with word boundaries before the answer is accepted.
4. **Fail closed** — Empty/unverified answers become `insufficient_information`. Request + DB statement timeouts bound hang risk.

## Why this shape

| Constraint | Choice                                                                                |
| ---------- | ------------------------------------------------------------------------------------- |
| 6 calls    | Headings + keyword intersection before `get_page`; overview never exceeds 1+5         |
| No RAG     | Exact keyword map + page text beats embeddings for short, citable policy/Q&A          |
| Grounding  | Exact quote check (not fuzzy); abstain if claims cannot be cited                      |
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
