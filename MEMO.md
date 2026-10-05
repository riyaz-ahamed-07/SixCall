# SixCall — one-page design memo

**Budgeted document Q&A without RAG.** SixCall answers questions over an ingested PDF using four tools (`list_documents`, `list_headings`, `search_keyword`, `get_page`) and a hard ceiling of **six tool calls** per question. There is no vector index and no agent framework. The demo path plans keywords locally and makes **one** main-model answer call (Gemini, then Groq). A second answer call happens only when the first abstains and a `get_page` is still left.

## Architecture

1. **Ingest** — PyMuPDF extracts immutable page text, TOC/font headings, and a stemmed inverted index. `doc_id` is `sha256(owner:bytes)[:16]` so tenants isolate identical files.
2. **Route** — Live asks use tools. A pure clarification can reuse prior quotes only when `SIXCALL_FOLLOWUPS=1`. Whole-document overview reads real pages (`get_page`). The light TOC summary is post-ingest only and is not served from `/ask`.
3. **Agent** — A local planner picks keywords (optional LLM planner is off). Budget: `1×list_headings + ≤2×search_keyword + ≤3–4×get_page ≤ 6`. Superseding questions force the latest keyword hit into the fetch window before heading boost. Multi/compare/supersede may read 4 pages; everything else reads 3, holding one call for a single repair re-draft. Evidence ids are capped per page.
4. **Fail closed** — Empty/unverified answers become `insufficient_information`. Request + DB statement timeouts bound hang risk.

## Why this shape

| Constraint | Choice                                                                                |
| ---------- | ------------------------------------------------------------------------------------- |
| 6 calls    | Headings + keyword intersection before `get_page`; overview never exceeds 1+5         |
| No RAG     | Exact keyword map + page text beats embeddings for short, citable policy/Q&A          |
| Grounding  | Evidence-id membership, else an exact span. Abstain if neither holds. Fuzzy match is not used. |
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
