"use client";

import {
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

type GlideMenuProps = {
  children: ReactNode;
  className?: string;
  highlightClassName?: string;
  rowSelector?: string;
};

export default function GlideMenu({
  children,
  className = "",
  highlightClassName = "inset-x-0 rounded-control bg-hover",
  rowSelector = "[data-menu-row]",
}: GlideMenuProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState<{ top: number; height: number } | null>(null);
  const [engaged, setEngaged] = useState(false);

  useLayoutEffect(() => {
    const root = rootRef.current;
    if (!root) return;

    const onMove = (event: PointerEvent) => {
      const target = (event.target as Element).closest(rowSelector);
      if (!target || !root.contains(target)) {
        setEngaged(false);
        return;
      }
      const el = target as HTMLElement;
      setBox({ top: el.offsetTop, height: el.offsetHeight });
      setEngaged(true);
    };

    const onLeave = () => setEngaged(false);
    root.addEventListener("pointermove", onMove);
    root.addEventListener("pointerleave", onLeave);
    return () => {
      root.removeEventListener("pointermove", onMove);
      root.removeEventListener("pointerleave", onLeave);
    };
  }, [rowSelector]);

  return (
    <div ref={rootRef} className={`group/glide-menu relative ${className}`}>
      <span
        aria-hidden
        className={`pointer-events-none absolute z-0 ${highlightClassName}`}
        style={{
          top: box?.top ?? 0,
          height: box?.height ?? 0,
          opacity: box && engaged ? 1 : 0,
          transition:
            "top 220ms cubic-bezier(0.23,1,0.32,1), height 220ms cubic-bezier(0.23,1,0.32,1), opacity 150ms ease",
        }}
      />
      {children}
    </div>
  );
}
