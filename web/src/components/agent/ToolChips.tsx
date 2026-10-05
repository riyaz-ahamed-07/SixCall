"use client";

import { useState, type ReactNode } from "react";
import type { ToolTraceStep } from "@/lib/api";

const Icons: Record<string, ReactNode> = {
  list_documents: (
    <g fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" />
    </g>
  ),
  list_headings: (
    <g fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <path d="M4 6h16M4 12h10M4 18h7" />
    </g>
  ),
  search_keyword: (
    <g fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <circle cx="11" cy="11" r="7" />
      <path d="M21 21l-4.3-4.3" />
    </g>
  ),
  get_page: (
    <g fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <path d="M14 2v6h6" />
    </g>
  ),
  think: <path d="M12 2l2.4 7.2L22 12l-7.6 2.8L12 22l-2.4-7.2L2 12l7.6-2.8z" />,
};

function chipFor(step: ToolTraceStep) {
  const args = step.args ?? {};
  if (typeof args.keyword === "string") return String(args.keyword);
  if (args.page_number !== undefined) return `page ${args.page_number}`;
  if (typeof args.doc_id === "string") return String(args.doc_id).slice(0, 10);
  return step.result_summary?.slice(0, 42) || "—";
}

export default function ToolChips({
  steps,
  labels,
}: {
  steps: ToolTraceStep[];
  labels?: { header?: string };
}) {
  const [open, setOpen] = useState(false);
  const [openRows, setOpenRows] = useState<Set<number>>(new Set());

  const header =
    labels?.header ??
    `${steps.length} tool call${steps.length === 1 ? "" : "s"} · budget 6`;

  return (
    <div className="w-full max-w-md pb-0.5">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
        className="-mx-1.5 flex w-fit items-center gap-1.5 rounded-control px-1.5 py-1 text-[12.5px] text-ink-2 transition-colors duration-100 hover:bg-hover-2"
      >
        <svg
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="transition-transform duration-200"
          style={{ transform: open ? "rotate(0deg)" : "rotate(-90deg)" }}
        >
          <path d="M6 9l6 6 6-6" />
        </svg>
        <span className="tabular-nums">{header}</span>
      </button>

      <div
        className="grid transition-[grid-template-rows,opacity] duration-300"
        style={{
          gridTemplateRows: open ? "1fr" : "0fr",
          opacity: open ? 1 : 0,
        }}
      >
        <div className="-mx-1 overflow-hidden px-1.5 pb-1">
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {steps.map((step, index) => {
              const tool = step.tool ?? "tool";
              const rowOpen = openRows.has(index);
              return (
                <div key={`${tool}-${index}`} className="min-w-0">
                  <button
                    type="button"
                    aria-expanded={rowOpen}
                    onClick={() =>
                      setOpenRows((current) => {
                        const next = new Set(current);
                        if (next.has(index)) next.delete(index);
                        else next.add(index);
                        return next;
                      })
                    }
                    className={`inline-flex max-w-full items-center gap-1.5 rounded-full border px-2 py-1 text-left transition-colors duration-100 ${
                      rowOpen
                        ? "border-line-strong bg-hover-2"
                        : "border-line bg-surface hover:bg-hover"
                    }`}
                  >
                    <span className="flex size-3.5 shrink-0 items-center justify-center text-ink-3">
                      <svg
                        width="12"
                        height="12"
                        viewBox="0 0 24 24"
                        fill={tool === "think" ? "currentColor" : "none"}
                        stroke="currentColor"
                      >
                        {Icons[tool] ?? Icons.think}
                      </svg>
                    </span>
                    <span className="shrink-0 text-[11.5px] font-medium text-ink">
                      {tool}
                    </span>
                    <span className="min-w-0 truncate font-mono text-[10.5px] text-ink-3">
                      {chipFor(step)}
                    </span>
                  </button>
                  <div
                    className="grid transition-[grid-template-rows,opacity] duration-300"
                    style={{
                      gridTemplateRows: rowOpen ? "1fr" : "0fr",
                      opacity: rowOpen ? 1 : 0,
                    }}
                  >
                    <div className="min-h-0 overflow-hidden">
                      <div className="mt-1 mb-1 max-w-xs rounded-[8px] bg-inset px-2.5 py-1.5 text-[11.5px] leading-relaxed text-ink-2">
                        {step.result_summary ||
                          (step.error ? `Error: ${step.error}` : "No summary")}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
