"use client";

import { useEffect, useState } from "react";

export type StreamingToken = { text: string; cite?: boolean };

export type StreamingSource = {
  name: string;
  domain: string;
  href?: string;
  excerpt?: string;
};

export default function StreamingText({
  content,
  sources = [],
  followUps = [],
  labels,
  fill = true,
  instant = true,
  onDone,
  onFollowUp,
  followUpsDisabled = false,
}: {
  content: StreamingToken[];
  sources?: StreamingSource[];
  followUps?: string[];
  labels?: { sources?: string; followUps?: string };
  fill?: boolean;
  /** When true (default), render full answer immediately — no artificial typing. */
  instant?: boolean;
  onDone?: () => void;
  onFollowUp?: (text: string, index: number) => void;
  followUpsDisabled?: boolean;
}) {
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const copy = {
    sources: labels?.sources ?? `${sources.length} sources`,
    followUps: labels?.followUps ?? "Follow-ups",
  };
  const text = content.map((token) => token.text).join("");

  useEffect(() => {
    onDone?.();
  }, [text, onDone]);

  return (
    <div className={fill ? "w-full" : "min-h-[15.5rem] w-full max-w-95"}>
      <p className="text-[14px] leading-[1.65] text-ink whitespace-pre-wrap">
        {instant
          ? text
          : content.map((token, i) =>
              token.cite ? (
                <span
                  key={i}
                  className="ml-0 mr-1 inline-flex h-4.5 translate-y-[-1px] items-center gap-1 rounded-[5px] bg-inset px-[3px] align-middle font-mono text-[10.5px] text-ink-2 shadow-hairline"
                >
                  {sources[0]?.domain ?? "source"}
                </span>
              ) : (
                <span key={i} className="inline">
                  {token.text}
                </span>
              ),
            )}
      </p>

      {sources.length > 0 && (
        <div className="mt-3 flex items-center gap-0.5">
          <button
            type="button"
            aria-expanded={sourcesOpen}
            onClick={() => setSourcesOpen((current) => !current)}
            className="flex items-center gap-1.5 rounded-[7px] bg-inset px-2 py-1 text-left transition-colors duration-150 hover:bg-hover-2"
          >
            <svg
              width="12"
              height="12"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              className="text-ink-3"
            >
              <path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" />
            </svg>
            <span className="text-[12px] font-medium text-ink-2">
              {copy.sources}
            </span>
            <svg
              width="12"
              height="12"
              viewBox="0 0 24 24"
              fill="none"
              stroke="var(--ink-3)"
              strokeWidth="2.2"
              className="transition-transform duration-200"
              style={{
                transform: sourcesOpen ? "rotate(180deg)" : "rotate(0)",
              }}
            >
              <path d="M6 9l6 6 6-6" />
            </svg>
          </button>
        </div>
      )}

      <div
        className="grid transition-[grid-template-rows,opacity] duration-300"
        style={{
          gridTemplateRows: sourcesOpen ? "1fr" : "0fr",
          opacity: sourcesOpen ? 1 : 0,
        }}
      >
        <div className="overflow-hidden">
          <div className="mt-2 flex flex-col gap-1.5">
            {sources.map((source, index) => (
              <div
                key={`${source.domain}-${source.name}-${index}`}
                className="rounded-[10px] border border-line bg-field/80 px-3 py-2"
              >
                <div className="flex items-center gap-2">
                  <span className="text-[12px] font-medium text-ink">
                    {source.name}
                  </span>
                  <span className="ml-auto rounded-full bg-surface px-1.5 py-0.5 font-mono text-[10.5px] text-ink-3 shadow-hairline">
                    {source.domain}
                  </span>
                </div>
                {source.excerpt ? (
                  <p className="mt-1 text-[12px] leading-relaxed text-ink-2 whitespace-pre-wrap">
                    “{source.excerpt}”
                  </p>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      </div>

      {followUps.length > 0 && (
        <div className="mt-3.5 border-t border-line pt-3">
          <p className="text-[11.5px] font-medium uppercase tracking-[0.06em] text-ink-3">
            {copy.followUps}
          </p>
          <div className="mt-1.5 flex flex-col gap-0.5">
            {followUps.map((item, i) => (
              <button
                key={item}
                type="button"
                disabled={followUpsDisabled}
                onClick={() => onFollowUp?.(item, i)}
                className="group -mx-1 flex items-center gap-2 rounded-[8px] px-1.5 py-1.5 text-left text-[12.5px] text-ink transition-colors duration-100 hover:bg-hover-2 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <svg
                  width="12"
                  height="12"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="var(--ink-3)"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className="shrink-0 transition-transform duration-150 group-hover:translate-x-0.5"
                >
                  <path d="M5 12h14M13 5l7 7-7 7" />
                </svg>
                {item}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
