import Link from "next/link";
import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Documentation · SixCall",
  description:
    "Enterprise documentation for SixCall — architecture, tools, budget, overview, and follow-ups.",
};

const SECTIONS = [
  { id: "overview", label: "Product overview" },
  { id: "architecture", label: "Architecture" },
  { id: "tools", label: "Document tools" },
  { id: "budget", label: "Budget & traces" },
  { id: "routes", label: "Ask · Overview · Follow-up" },
  { id: "pipeline", label: "Evidence pipeline" },
  { id: "api", label: "HTTP API" },
  { id: "security", label: "Security posture" },
  { id: "limits", label: "Limits & honesty" },
] as const;

export default function DocsPage() {
  return (
    <div className="relative min-h-dvh bg-canvas text-ink">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 app-ambient opacity-80"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-[480px] app-grid opacity-40"
      />

      <header className="relative z-20 border-b border-line/80 bg-canvas/80 backdrop-blur-md">
        <div className="mx-auto flex w-full max-w-6xl items-center justify-between px-6 py-4">
          <Link href="/" className="flex items-center gap-2.5">
            <span className="flex size-8 items-center justify-center rounded-[9px] bg-ink text-[12px] font-bold text-surface shadow-btn">
              6
            </span>
            <div>
              <p className="text-[15px] font-semibold tracking-[-0.02em]">
                SixCall
              </p>
              <p className="text-[11px] text-ink-3">Technical documentation</p>
            </div>
          </Link>
          <nav className="flex items-center gap-2">
            <Link
              href="/app"
              className="rounded-[8px] px-3 py-1.5 text-[13px] font-medium text-ink-2 transition hover:bg-hover-2 hover:text-ink"
            >
              Open app
            </Link>
            <Link
              href="/login"
              className="rounded-[8px] bg-ink px-3 py-1.5 text-[13px] font-medium text-surface shadow-btn transition hover:opacity-90"
            >
              Sign in
            </Link>
          </nav>
        </div>
      </header>

      <div className="relative z-10 mx-auto grid w-full max-w-6xl gap-10 px-6 py-10 lg:grid-cols-[220px_minmax(0,1fr)] lg:py-14">
        <aside className="lg:sticky lg:top-8 lg:self-start">
          <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-ink-3">
            Contents
          </p>
          <nav className="mt-3 flex flex-col gap-1">
            {SECTIONS.map((s) => (
              <a
                key={s.id}
                href={`#${s.id}`}
                className="rounded-[8px] px-2.5 py-1.5 text-[13px] text-ink-2 transition hover:bg-hover-2 hover:text-ink"
              >
                {s.label}
              </a>
            ))}
          </nav>
        </aside>

        <article className="min-w-0">
          <section id="overview" className="scroll-mt-8">
            <p className="text-[11.5px] font-medium uppercase tracking-[0.14em] text-ink-3">
              SixCall Documentation
            </p>
            <h1 className="mt-3 text-[36px] font-semibold tracking-[-0.035em] text-ink sm:text-[44px]">
              Budgeted document answering, end to end
            </h1>
            <p className="mt-4 max-w-2xl text-[15.5px] leading-relaxed text-ink-2">
              SixCall answers questions against ingested PDFs using exactly four
              document tools and a hard six-call budget per question. It prefers
              lexical search and table-of-contents structure over embeddings,
              and abstains when evidence is insufficient.
            </p>
            <div className="mt-6 grid gap-3 sm:grid-cols-3">
              {[
                [
                  "4 tools",
                  "list_documents · list_headings · get_page · search_keyword",
                ],
                ["6 calls", "Hard ceiling per question; 7th call refused"],
                ["Abstain", "Insufficient evidence → no invented answers"],
              ].map(([t, b]) => (
                <div
                  key={t}
                  className="rounded-[14px] border border-line bg-surface/90 px-4 py-3.5 shadow-hairline"
                >
                  <p className="text-[13px] font-semibold text-ink">{t}</p>
                  <p className="mt-1 text-[12.5px] leading-relaxed text-ink-2">
                    {b}
                  </p>
                </div>
              ))}
            </div>
          </section>

          <Hr />

          <section id="architecture" className="scroll-mt-8">
            <H2>Architecture</H2>
            <p className="mt-3 max-w-2xl text-[14.5px] leading-relaxed text-ink-2">
              The system is split into a tool/store layer and an agent layer.
              The agent never imports the store directly — it only calls the
              four tool functions, which are wrapped by a request-local budget
              session.
            </p>
            <pre className="mt-5 overflow-x-auto rounded-[14px] border border-line bg-ink px-4 py-4 font-mono text-[11.5px] leading-relaxed text-surface/90">
              {`PDF ──ingest──► DocumentStore (pages · headings · keyword index)
                      ▲
                      │  tools only
CLI / UI / HTTP ──► Agent ──► wrapper (max 6) ──► 4 tools
                      │
                      ├── overview   (headings + ≤5 pages)
                      ├── follow-up  (chat context, 0 tools)
                      └── ask        (plan → search → score → pages → answer)`}
            </pre>
            <ul className="mt-5 space-y-2 text-[14px] leading-relaxed text-ink-2">
              <li>
                <strong className="text-ink">Store</strong> — PyMuPDF ingest,
                immutable page text, TOC/font headings, inverted keyword map.
              </li>
              <li>
                <strong className="text-ink">Tools</strong> — Thin, fail-closed
                wrappers; every call is counted and traced.
              </li>
              <li>
                <strong className="text-ink">Agent</strong> — Deterministic
                routing + local scoring + one final model generation + exact
                quote verification.
              </li>
            </ul>
          </section>

          <Hr />

          <section id="tools" className="scroll-mt-8">
            <H2>Document tools</H2>
            <div className="mt-4 overflow-hidden rounded-[14px] border border-line bg-surface shadow-hairline">
              <table className="w-full text-left text-[13px]">
                <thead className="border-b border-line bg-inset/80 text-[11.5px] uppercase tracking-[0.06em] text-ink-3">
                  <tr>
                    <th className="px-4 py-2.5 font-medium">Tool</th>
                    <th className="px-4 py-2.5 font-medium">Returns</th>
                    <th className="px-4 py-2.5 font-medium">Notes</th>
                  </tr>
                </thead>
                <tbody className="text-ink-2">
                  {[
                    ["list_documents", "Titles + metadata", "No page text"],
                    [
                      "list_headings",
                      "title, level, start–end",
                      "Document tree / TOC",
                    ],
                    [
                      "search_keyword",
                      "Sorted page numbers only",
                      "Aliases expand inside one call",
                    ],
                    [
                      "get_page",
                      "Text of exactly one page",
                      "1-based page index",
                    ],
                  ].map(([a, b, c]) => (
                    <tr
                      key={a}
                      className="border-b border-line/80 last:border-0"
                    >
                      <td className="px-4 py-3 font-mono text-[12.5px] text-ink">
                        {a}
                      </td>
                      <td className="px-4 py-3">{b}</td>
                      <td className="px-4 py-3">{c}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <Hr />

          <section id="budget" className="scroll-mt-8">
            <H2>Budget & traces</H2>
            <p className="mt-3 max-w-2xl text-[14.5px] leading-relaxed text-ink-2">
              Each question starts a request-local session (ContextVar) bound to
              a document ID. Calls are reserved before execution; failures still
              consume budget. A seventh call is refused. Traces persist to disk
              and optionally Postgres for replay.
            </p>
            <ul className="mt-4 list-disc space-y-1.5 pl-5 text-[14px] text-ink-2">
              <li>Hard ceiling: 6 tool calls (env cannot raise above 6).</li>
              <li>Tools fail closed without an active session.</li>
              <li>Concurrent requests do not share a global session.</li>
            </ul>
          </section>

          <Hr />

          <section id="routes" className="scroll-mt-8">
            <H2>Ask · Overview · Follow-up</H2>
            <div className="mt-4 grid gap-3">
              <Card
                title="Ask (default)"
                body="list_headings → planner keywords → search_keyword → local tree∩keyword score → get_page ×N → one answer → exact quote verify."
              />
              <Card
                title="Overview"
                body="For “What is this document about?” / “Give a summary”: list_headings, then up to five get_page calls (intro, major sections, conclusion), then one summary answer. Also available as POST /overview."
              />
              <Card
                title="Follow-up"
                body="When prior chat history is present and the user continues (“explain that”, “which page?”, short clarifications), SixCall answers from conversation context with zero document tools (calls_used = 0). New factual lookups still take the full tool path."
              />
            </div>
          </section>

          <Hr />

          <section id="pipeline" className="scroll-mt-8">
            <H2>Evidence pipeline</H2>
            <ol className="mt-4 list-decimal space-y-2 pl-5 text-[14px] leading-relaxed text-ink-2">
              <li>
                Planner proposes keywords and heading hints (or overview selects
                pages from TOC).
              </li>
              <li>
                Scorer prefers pages in both keyword hits and heading ranges.
              </li>
              <li>
                Fetched pages are treated as untrusted data; injection-like
                lines are flagged.
              </li>
              <li>
                One final model generation (no JSON-repair LLM, no redraft
                loop).
              </li>
              <li>
                Quotes must be exact contiguous word-bounded spans of fetched
                pages.
              </li>
              <li>
                Empty answers and substring false-positives (e.g. “eligible” in
                “ineligible”) are rejected.
              </li>
            </ol>
          </section>

          <Hr />

          <section id="api" className="scroll-mt-8">
            <H2>HTTP API</H2>
            <div className="mt-4 overflow-hidden rounded-[14px] border border-line bg-surface shadow-hairline">
              <table className="w-full text-left text-[13px]">
                <thead className="border-b border-line bg-inset/80 text-[11.5px] uppercase tracking-[0.06em] text-ink-3">
                  <tr>
                    <th className="px-4 py-2.5 font-medium">Method</th>
                    <th className="px-4 py-2.5 font-medium">Path</th>
                    <th className="px-4 py-2.5 font-medium">Purpose</th>
                  </tr>
                </thead>
                <tbody className="text-ink-2">
                  {[
                    ["POST", "/ingest", "Upload PDF → doc_id"],
                    ["POST", "/ask", "Question (+ optional history)"],
                    ["POST", "/overview", "Forced document overview"],
                    ["GET", "/documents", "List ingested docs"],
                    ["GET", "/trace/{id}", "Tool trace for a question"],
                    ["GET", "/health", "Liveness + store count"],
                  ].map(([m, p, d]) => (
                    <tr
                      key={p}
                      className="border-b border-line/80 last:border-0"
                    >
                      <td className="px-4 py-3 font-mono text-[12px] text-ink">
                        {m}
                      </td>
                      <td className="px-4 py-3 font-mono text-[12.5px]">{p}</td>
                      <td className="px-4 py-3">{d}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-4 text-[13.5px] leading-relaxed text-ink-2">
              CLI equivalents:{" "}
              <code className="rounded bg-inset px-1.5 py-0.5 font-mono text-[12px]">
                python -m app.cli ingest|ask|overview|docs|trace
              </code>
            </p>
          </section>

          <Hr />

          <section id="security" className="scroll-mt-8">
            <H2>Security posture</H2>
            <ul className="mt-3 list-disc space-y-1.5 pl-5 text-[14px] text-ink-2">
              <li>
                Page text is untrusted; prompt-injection patterns are flagged.
              </li>
              <li>
                Capabilities and budgets are enforced in code, not prompt text.
              </li>
              <li>
                Localhost demo may run without auth; shared deployments should
                use session auth + ownership.
              </li>
              <li>
                Never reuse prior answers as free document evidence for a new
                lookup.
              </li>
            </ul>
          </section>

          <Hr />

          <section id="limits" className="scroll-mt-8 pb-16">
            <H2>Limits & honesty</H2>
            <p className="mt-3 max-w-2xl text-[14.5px] leading-relaxed text-ink-2">
              Six calls cannot cover arbitrary multi-hop questions. The correct
              behavior is calibrated abstention. Lexical search misses true
              synonyms. Charts without OCR text cannot be answered. Later page
              numbers are not authority — amendments need explicit dates or
              supersession language in the fetched evidence.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link
                href="/app"
                className="rounded-[10px] bg-ink px-4 py-2.5 text-[14px] font-medium text-surface shadow-btn transition hover:opacity-90"
              >
                Open product
              </Link>
              <Link
                href="/"
                className="rounded-[10px] border border-line bg-surface px-4 py-2.5 text-[14px] font-medium text-ink transition hover:bg-hover"
              >
                Back to home
              </Link>
            </div>
          </section>
        </article>
      </div>
    </div>
  );
}

function H2({ children }: { children: ReactNode }) {
  return (
    <h2 className="text-[22px] font-semibold tracking-[-0.025em] text-ink">
      {children}
    </h2>
  );
}

function Hr() {
  return <hr className="my-10 border-line/80" />;
}

function Card({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-[14px] border border-line bg-surface/90 px-4 py-4 shadow-hairline">
      <p className="text-[14px] font-semibold tracking-[-0.01em] text-ink">
        {title}
      </p>
      <p className="mt-1.5 text-[13.5px] leading-relaxed text-ink-2">{body}</p>
    </div>
  );
}
