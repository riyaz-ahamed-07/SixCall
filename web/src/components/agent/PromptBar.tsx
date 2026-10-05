"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";

function Icon({
  children,
  size = 15,
  strokeWidth = 1.8,
}: {
  children: React.ReactNode;
  size?: number;
  strokeWidth?: number;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

export default function PromptBar({
  placeholder = "Ask about this document…",
  disabled = false,
  onSend,
  onAttach,
}: {
  placeholder?: string;
  disabled?: boolean;
  onSend?: (text: string) => void;
  onAttach?: (file: File) => void;
}) {
  const [draft, setDraft] = useState("");
  const [expanded, setExpanded] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const measureRef = useRef<HTMLSpanElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const controlsRef = useRef<HTMLDivElement>(null);

  const canSend = draft.trim().length > 0 && !disabled;

  const send = () => {
    if (!canSend) return;
    onSend?.(draft.trim());
    setDraft("");
  };

  useLayoutEffect(() => {
    const input = inputRef.current;
    const measure = measureRef.current;
    const controls = controlsRef.current;
    if (!input || !measure || !controls) return;

    const inlineInputWidth = controls.clientWidth - 28 * 3 - 16;
    const needsFullWidth =
      draft.includes("\n") || measure.offsetWidth + 8 > inlineInputWidth;
    if (needsFullWidth !== expanded) setExpanded(needsFullWidth);

    input.style.height = "0px";
    const contentHeight = input.scrollHeight;
    input.style.height = `${Math.min(Math.max(contentHeight, 28), 100)}px`;
  }, [draft, expanded]);

  useEffect(() => {
    if (!disabled) inputRef.current?.focus();
  }, [disabled]);

  return (
    <div className="w-full">
      <div
        className={`prompt-shell relative isolate flex flex-col overflow-hidden border border-line bg-surface shadow-card gap-1.5 p-1.5 ${
          expanded ? "rounded-[16px]" : "rounded-[16px]"
        }`}
      >
        <span
          ref={measureRef}
          aria-hidden="true"
          className="pointer-events-none absolute invisible whitespace-pre text-[13px] leading-[18px]"
        >
          {draft}
        </span>

        <div
          ref={controlsRef}
          className={`grid items-end gap-x-1 gap-y-1.5 ${
            expanded
              ? "grid-cols-[28px_auto_minmax(0,1fr)_28px]"
              : "grid-cols-[28px_minmax(0,1fr)_28px_28px]"
          }`}
        >
          <button
            type="button"
            aria-label="Upload PDF"
            disabled={disabled}
            onClick={() => fileRef.current?.click()}
            className={`flex size-7 shrink-0 items-center justify-center justify-self-start rounded-[8px] text-ink-3 transition-[background-color,color,transform] duration-150 hover:bg-hover hover:text-ink active:scale-[0.94] disabled:opacity-40 ${
              expanded ? "col-start-1 row-start-2" : "col-start-1 row-start-1"
            }`}
          >
            <Icon size={16} strokeWidth={2}>
              <path d="M12 5v14M5 12h14" />
            </Icon>
          </button>
          <input
            ref={fileRef}
            type="file"
            accept="application/pdf,.pdf"
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) onAttach?.(file);
              event.target.value = "";
            }}
          />

          <textarea
            ref={inputRef}
            rows={1}
            value={draft}
            disabled={disabled}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (
                event.key === "Enter" &&
                !event.shiftKey &&
                !event.nativeEvent.isComposing
              ) {
                event.preventDefault();
                send();
              }
            }}
            placeholder={placeholder}
            aria-label="Prompt"
            className={`min-h-7 min-w-0 w-full resize-none bg-transparent px-1 py-[5px] text-[13px] leading-[18px] text-ink outline-none [overflow-wrap:anywhere] placeholder:text-ink-3 disabled:opacity-50 ${
              expanded
                ? "col-span-full col-start-1 row-start-1"
                : "col-start-2 row-start-1"
            }`}
          />

          <button
            type="button"
            aria-label="Send"
            disabled={!canSend}
            onClick={send}
            className={`flex size-7 shrink-0 items-center justify-center rounded-[8px] transition-[background-color,color,transform] duration-200 enabled:active:scale-[0.94] ${
              expanded ? "col-start-4 row-start-2" : "col-start-4 row-start-1"
            }`}
            style={{
              background: canSend ? "var(--accent)" : "var(--line-strong)",
              color: canSend ? "#ffffff" : "var(--ink-2)",
            }}
          >
            <Icon size={16} strokeWidth={2.4}>
              <path d="M12 19V5M5 12l7-7 7 7" />
            </Icon>
          </button>
        </div>
      </div>
    </div>
  );
}
