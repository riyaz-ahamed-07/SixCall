"use client";

export default function BudgetMeter({
  used = 0,
  total = 6,
  label = true,
}: {
  used?: number;
  total?: number;
  label?: boolean;
}) {
  const capped = Math.max(0, Math.min(total, used));
  const remaining = total - capped;
  const tight = remaining <= 1 && capped > 0;

  return (
    <div
      className="inline-flex items-center gap-2 rounded-full bg-field px-2.5 py-1 shadow-hairline"
      title={`${capped} of ${total} tool calls used`}
    >
      <span className="flex items-center gap-[3px]" aria-hidden>
        {Array.from({ length: total }, (_, i) => {
          const filled = i < capped;
          return (
            <span
              key={i}
              className="h-[7px] w-[7px] rounded-[2px] transition-colors duration-300"
              style={{
                background: filled
                  ? tight
                    ? "var(--red)"
                    : "var(--accent)"
                  : "var(--line-strong)",
                opacity: filled ? 1 : 0.55,
              }}
            />
          );
        })}
      </span>
      {label ? (
        <span
          className={`text-[11.5px] font-medium tabular-nums ${
            tight ? "text-orange" : "text-ink-2"
          }`}
        >
          {capped}/{total}
        </span>
      ) : null}
    </div>
  );
}
