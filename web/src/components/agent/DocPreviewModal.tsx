"use client";

import { useEffect, useState } from "react";
import { fetchDocumentPdfBlob } from "@/lib/api";
import { formatDocName } from "@/lib/docs";
import type { DocSummary } from "@/lib/api";

export default function DocPreviewModal({
  doc,
  open,
  onClose,
}: {
  doc: DocSummary | null;
  open: boolean;
  onClose: () => void;
}) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  useEffect(() => {
    if (!open || !doc?.doc_id) return;
    let cancelled = false;
    let objectUrl: string | null = null;
    setLoading(true);
    setError(null);
    setBlobUrl(null);
    void fetchDocumentPdfBlob(doc.doc_id)
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setBlobUrl(objectUrl);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Preview failed");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [open, doc?.doc_id]);

  if (!open || !doc) return null;

  const title = formatDocName(doc);
  const pageCount = doc.page_count;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/45 p-4 backdrop-blur-[2px]"
      role="dialog"
      aria-modal="true"
      aria-label={`Preview ${title}`}
      onClick={onClose}
    >
      <div
        className="flex h-[min(90dvh,900px)] w-full max-w-5xl flex-col overflow-hidden rounded-[16px] border border-line bg-surface shadow-overlay"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-line px-4 py-3">
          <div className="min-w-0">
            <p className="truncate text-[15px] font-semibold tracking-[-0.02em] text-ink">
              {title}
            </p>
            <p className="mt-0.5 text-[12px] text-ink-3 tabular-nums">
              {pageCount != null ? `${pageCount} pages · ` : ""}
              original PDF preview
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex size-8 shrink-0 items-center justify-center rounded-[8px] text-ink-3 transition hover:bg-hover-2 hover:text-ink"
            aria-label="Close preview"
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </div>

        <div className="relative min-h-0 flex-1 bg-inset">
          {loading ? (
            <p className="p-6 text-[13px] text-ink-3">Loading PDF…</p>
          ) : error ? (
            <div className="space-y-3 p-6">
              <p className="rounded-[8px] bg-red-tint px-3 py-2 text-[13px] text-red">
                {error}
              </p>
              <p className="text-[13px] text-ink-2">
                Re-upload this PDF once — originals are now stored for preview.
              </p>
            </div>
          ) : blobUrl ? (
            <iframe
              title={title}
              src={`${blobUrl}#toolbar=1&navpanes=1&view=FitH`}
              className="h-full w-full border-0 bg-white"
            />
          ) : null}
        </div>
      </div>
    </div>
  );
}
