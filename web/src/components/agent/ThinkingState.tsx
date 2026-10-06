"use client";

import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

type Row = {
  primary: string;
  secondary?: string;
  mono?: boolean;
};

/** While working, reveal one step at a time so earlier checks aren't instant. */
const STEP_MS = 1200;

export default function ThinkingState({
  rows,
  active = "Working",
  done = "Done",
  icon,
  working = false,
}: {
  rows: Row[];
  active?: string;
  done?: string;
  icon?: ReactNode;
  working?: boolean;
  onSettled?: () => void;
}) {
  const [manualExpanded, setManualExpanded] = useState<boolean | null>(null);
  const [tick, setTick] = useState(0);
  // Open while working; stay collapsed after settle unless the user expands.
  const autoExpanded = working;
  const expanded = manualExpanded ?? autoExpanded;
  const traceRef = useRef<HTMLDivElement>(null);
  const [lineHeight, setLineHeight] = useState(0);

  useEffect(() => {
    if (!working) return;
    let cancelled = false;
    const resetTimer = window.setTimeout(() => {
      if (!cancelled) setTick(0);
    }, 0);
    if (rows.length <= 1) {
      return () => {
        cancelled = true;
        window.clearTimeout(resetTimer);
      };
    }
    const interval = window.setInterval(() => {
      setTick((s) => (s + 1 >= rows.length ? s : s + 1));
    }, STEP_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(resetTimer);
      window.clearInterval(interval);
    };
  }, [working, rows.length]);

  const stage = working ? Math.min(tick + 1, rows.length) : rows.length;
  const visibleCount = working
    ? Math.min(Math.max(stage, 1), rows.length || 1)
    : rows.length;
  const visibleRows = rows.slice(0, visibleCount);
  const activeIndex = working ? visibleCount - 1 : -1;

  useLayoutEffect(() => {
    if (traceRef.current) setLineHeight(traceRef.current.offsetHeight);
  }, [visibleCount, expanded, rows]);

  return (
    <div className="flex w-full max-w-95 flex-col">
      <button
        type="button"
        aria-expanded={expanded}
        onClick={() =>
          setManualExpanded((current) => !(current ?? autoExpanded))
        }
        className="-mx-1.5 flex w-fit items-center gap-2 rounded-control px-1.5 py-1 transition-colors duration-100 hover:bg-hover-2"
      >
        {icon ?? (
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill={working ? "var(--ink-2)" : "var(--ink-3)"}
          >
            <path d="M12 2l2.4 7.2L22 12l-7.6 2.8L12 22l-2.4-7.2L2 12l7.6-2.8z" />
          </svg>
        )}
        <span role="status" className="contents">
          {working ? (
            <span
              className="bg-clip-text text-[13px] font-medium whitespace-nowrap text-transparent"
              style={{
                backgroundImage:
                  "linear-gradient(90deg, var(--ink-3) 35%, var(--ink) 50%, var(--ink-3) 65%)",
                backgroundSize: "200% 100%",
                animation: "shimmer-text 1.4s linear infinite",
              }}
            >
              {active}
            </span>
          ) : (
            <span className="text-[13px] font-medium whitespace-nowrap text-ink-2">
              {done}
            </span>
          )}
        </span>
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="var(--ink-3)"
          strokeWidth="2.2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="transition-transform duration-300"
          style={{ transform: expanded ? "rotate(180deg)" : "rotate(0)" }}
        >
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>

      <div
        className="grid transition-[grid-template-rows,opacity] duration-400"
        style={{
          gridTemplateRows: expanded ? "1fr" : "0fr",
          opacity: expanded ? 1 : 0,
          transitionTimingFunction: "cubic-bezier(0.23, 1, 0.32, 1)",
        }}
      >
        <div className="overflow-hidden">
          <div className="relative mt-1 ml-[5px] pl-4">
            <span
              aria-hidden
              className="absolute left-[3px] w-px bg-line"
              style={{
                top: -8,
                height: lineHeight ? lineHeight - 2 : 0,
                transition: "height 500ms cubic-bezier(0.23,1,0.32,1)",
              }}
            />
            <div ref={traceRef} className="flex flex-col gap-1 py-1">
              {visibleRows.map((row, i) => {
                const isActive = i === activeIndex;
                return (
                  <div
                    key={`${row.primary}-${i}`}
                    className="flex min-h-7 w-full items-center gap-2 rounded-[6px] px-1.5 py-0.5 text-left"
                    style={{
                      animation: working
                        ? `fade-up 280ms cubic-bezier(0.23,1,0.32,1) both`
                        : undefined,
                    }}
                  >
                    {isActive ? (
                      <span
                        className="size-3 shrink-0 rounded-full border-[1.5px] border-line-strong border-t-ink-2"
                        style={{ animation: "spin 700ms linear infinite" }}
                      />
                    ) : (
                      <svg
                        width="14"
                        height="14"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="var(--ink-3)"
                        strokeWidth="2.5"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        className="shrink-0"
                      >
                        <path d="M20 6L9 17l-5-5" />
                      </svg>
                    )}
                    <span
                      className={`min-w-0 truncate text-[12.5px] font-medium ${isActive ? "text-ink" : "text-ink"}`}
                    >
                      {row.primary}
                    </span>
                    {row.secondary && (
                      <span
                        className={`shrink-0 text-[11.5px] text-ink-3 ${row.mono ? "font-mono" : ""}`}
                      >
                        {row.secondary}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
