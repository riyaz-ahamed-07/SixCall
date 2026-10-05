"use client";

import { useEffect, useState } from "react";
import LoadingState from "@/components/agent/LoadingState";

const STEPS = [
  "Receiving PDF",
  "Extracting pages",
  "Building headings & index",
  "Saving document",
];

const STEP_MS = 900;

export default function UploadProgress({
  filename,
}: {
  filename: string;
}) {
  const [stage, setStage] = useState(1);

  useEffect(() => {
    setStage(1);
    const t = setInterval(() => {
      setStage((s) => (s >= STEPS.length ? s : s + 1));
    }, STEP_MS);
    return () => clearInterval(t);
  }, [filename]);

  const visible = STEPS.slice(0, Math.min(stage, STEPS.length));

  return (
    <div
      role="status"
      className="rounded-[16px] border border-dashed border-line-strong bg-surface/90 px-4 py-3.5 shadow-hairline"
    >
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-[10px] bg-ink text-[11px] font-bold text-surface">
          PDF
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[12px] font-medium uppercase tracking-[0.08em] text-ink-3">
            Uploading document
          </p>
          <p className="mt-0.5 truncate text-[14px] font-semibold tracking-[-0.015em] text-ink">
            {filename}
          </p>
          <div className="mt-3">
            <LoadingState label="Ingesting" variant="Drive" />
          </div>
          <ul className="mt-3 flex flex-col gap-1.5 border-t border-line pt-3">
            {visible.map((label, i) => {
              const active = i === visible.length - 1 && stage <= STEPS.length;
              const done = i < visible.length - 1 || stage > STEPS.length;
              return (
                <li
                  key={label}
                  className="flex items-center gap-2 text-[12.5px]"
                  style={{
                    animation: "fade-up 280ms cubic-bezier(0.23,1,0.32,1) both",
                  }}
                >
                  {active ? (
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
                      stroke={done ? "var(--green)" : "var(--ink-3)"}
                      strokeWidth="2.5"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      className="shrink-0"
                    >
                      <path d="M20 6L9 17l-5-5" />
                    </svg>
                  )}
                  <span className={active ? "font-medium text-ink" : "text-ink-2"}>
                    {label}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      </div>
    </div>
  );
}
