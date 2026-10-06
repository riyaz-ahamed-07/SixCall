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
  fill = true,
  instant = true,
  onDone,
}: {
  content: StreamingToken[];
  sources?: StreamingSource[];
  fill?: boolean;
  /** When true (default), render full answer immediately — no artificial typing. */
  instant?: boolean;
  onDone?: () => void;
}) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const text = content.map((token) => token.text).join("");

  useEffect(() => {
    onDone?.();
  }, [text, onDone]);

  return (
    <div className={fill ? "w-full" : "min-h-[15.5rem] w-full max-w-95"}>
      <p className="text-[14px] leading-[1.65] text-ink whitespace-pre-wrap">
        {instant ? (
          <>
            {text}
            {sources.length > 0 ? (
              <>
                {" "}
                {sources.map((source, index) => (
                  <CiteMark
                    key={`${source.domain}-${index}`}
                    index={index}
                    source={source}
                    active={hoverIndex === index}
                    onEnter={() => setHoverIndex(index)}
                    onLeave={() =>
                      setHoverIndex((current) =>
                        current === index ? null : current,
                      )
                    }
                  />
                ))}
              </>
            ) : null}
          </>
        ) : (
          content.map((token, i) =>
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
          )
        )}
      </p>
    </div>
  );
}

function previewExcerpt(text: string, max = 140): string {
  const cleaned = text.replace(/\s+/g, " ").trim();
  if (cleaned.length <= max) return cleaned;
  return `${cleaned.slice(0, max - 1).trimEnd()}…`;
}

function CiteMark({
  index,
  source,
  active,
  onEnter,
  onLeave,
}: {
  index: number;
  source: StreamingSource;
  active: boolean;
  onEnter: () => void;
  onLeave: () => void;
}) {
  const n = index + 1;
  const excerpt = source.excerpt ? previewExcerpt(source.excerpt) : null;
  return (
    <span
      className="relative mx-0.5 inline-block align-baseline"
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
      onFocus={onEnter}
      onBlur={onLeave}
    >
      <button
        type="button"
        className={`inline-flex h-[1.1rem] min-w-[1.1rem] translate-y-[-0.15em] items-center justify-center rounded-[4px] px-1 font-mono text-[10px] font-medium leading-none transition-colors ${
          active
            ? "bg-accent text-white"
            : "bg-inset text-ink-2 hover:bg-hover-2"
        }`}
        aria-label={
          excerpt
            ? `Reference ${n}, ${source.domain}: ${excerpt}`
            : `Reference ${n}, ${source.domain}`
        }
      >
        {n}
      </button>
      {active ? (
        <span
          role="tooltip"
          className="pointer-events-none absolute bottom-[calc(100%+6px)] left-1/2 z-20 w-max max-w-[16rem] -translate-x-1/2 rounded-[8px] border border-line bg-surface px-2.5 py-1.5 text-left shadow-hairline"
        >
          {excerpt ? (
            <span className="block text-[11px] leading-snug text-ink">
              “{excerpt}”
            </span>
          ) : (
            <span className="block text-[11px] font-medium text-ink">
              Ref {n}
            </span>
          )}
          <span className="mt-0.5 block font-mono text-[10.5px] text-ink-3">
            {source.domain}
          </span>
        </span>
      ) : null}
    </span>
  );
}
