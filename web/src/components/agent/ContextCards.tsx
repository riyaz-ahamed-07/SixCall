"use client";

import type { DocSummary } from "@/lib/api";
import { formatDocName } from "@/lib/docs";

export default function ContextCards({
  docs,
  activeDocId,
  emptyHint,
  onPick,
  onUpload,
}: {
  docs: DocSummary[];
  activeDocId?: string | null;
  emptyHint?: string;
  onPick?: (doc: DocSummary) => void;
  onUpload?: () => void;
}) {
  if (!docs.length) {
    return (
      <div className="flex w-full max-w-md flex-col gap-2">
        <button
          type="button"
          onClick={onUpload}
          className="group overflow-hidden rounded-[16px] border border-dashed border-accent/45 bg-surface text-left shadow-raised transition duration-200 hover:-translate-y-0.5 hover:border-accent hover:bg-accent-tint focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/35"
        >
          <div className="px-4 py-5">
            <div className="mb-3 flex size-9 items-center justify-center rounded-[10px] bg-accent text-[12px] font-bold text-white shadow-btn transition group-hover:scale-[1.04]">
              PDF
            </div>
            <p className="text-[14px] font-semibold tracking-[-0.01em] text-ink">
              Drop in a document for this chat
            </p>
            <p className="mt-1.5 text-[13px] leading-relaxed text-ink-2">
              {emptyHint ??
                "Click to upload a PDF. It stays in this chat only — other chats keep their own files."}
            </p>
            <span className="mt-3 inline-flex items-center gap-1.5 rounded-[8px] bg-accent px-3 py-1.5 text-[12.5px] font-semibold text-white shadow-btn">
              Upload PDF
              <svg
                width="12"
                height="12"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.4"
              >
                <path d="M12 5v14M5 12h14" />
              </svg>
            </span>
          </div>
        </button>
      </div>
    );
  }

  return (
    <div className="flex w-full max-w-md flex-col gap-2.5">
      <div className="flex items-center gap-2 px-0.5">
        <span className="text-[12px] font-medium uppercase tracking-[0.08em] text-ink-3">
          Document in this chat
        </span>
        <span className="inline-flex h-5 items-center rounded-md bg-inset px-1.5 text-[11.5px] font-medium text-ink-2 shadow-hairline tabular-nums">
          {docs.length}
        </span>
      </div>
      <div className="grid gap-2">
        {docs.map((doc, i) => {
          const title = formatDocName(doc);
          const active = doc.doc_id === activeDocId;
          return (
            <button
              key={doc.doc_id}
              type="button"
              onClick={() => onPick?.(doc)}
              className={`overflow-hidden rounded-[14px] border bg-surface text-left shadow-card transition duration-150 ${
                active
                  ? "border-accent/50 ring-2 ring-accent/20"
                  : "border-line hover:border-accent/35 hover:bg-hover"
              }`}
              style={{
                animation: `fade-up 400ms cubic-bezier(0.23,1,0.32,1) ${i * 70}ms both`,
              }}
            >
              <div className="flex items-start gap-2.5 px-3 py-3">
                <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-[8px] bg-accent-tint text-accent shadow-hairline">
                  <svg
                    width="13"
                    height="13"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                  >
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                    <path d="M14 2v6h6" />
                  </svg>
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[13px] font-medium text-ink">
                    {title}
                  </p>
                  <p className="mt-0.5 text-[11.5px] text-ink-3 tabular-nums">
                    {doc.page_count ? `${doc.page_count} pages` : "PDF"} ·
                    scoped to this chat
                  </p>
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
