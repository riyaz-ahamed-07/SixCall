"use client";

import type { ButtonHTMLAttributes, ReactNode } from "react";

export type ButtonVariant =
  | "primary"
  | "secondary"
  | "accent"
  | "ghost"
  | "quiet"
  | "success";

type ButtonSize = "xs" | "sm" | "md";

const VARIANT: Record<ButtonVariant, string> = {
  primary:
    "bg-accent text-white shadow-btn hover:bg-accent-ink disabled:bg-line-strong disabled:text-ink-2 disabled:shadow-none",
  secondary:
    "bg-field text-ink shadow-hairline hover:bg-hover disabled:opacity-50",
  accent:
    "bg-accent text-white shadow-btn hover:bg-accent-ink disabled:bg-line-strong disabled:text-ink-2 disabled:shadow-none",
  ghost:
    "bg-transparent text-ink-2 hover:bg-hover-2 hover:text-ink disabled:opacity-40",
  quiet:
    "bg-transparent text-ink-2 hover:bg-hover-2 hover:text-ink disabled:opacity-40",
  success: "bg-green text-white hover:opacity-90",
};

const SIZE: Record<ButtonSize, string> = {
  xs: "h-7 gap-1 rounded-full px-2.5 text-[12.5px]",
  sm: "h-7 gap-1 rounded-full px-3 text-[12.5px]",
  md: "h-8 gap-1.5 rounded-control px-3.5 text-[13px]",
};

export function Button({
  variant = "primary",
  size = "md",
  className = "",
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  children?: ReactNode;
}) {
  return (
    <button
      type="button"
      className={`inline-flex items-center justify-center font-medium transition-[background-color,opacity,transform,color] duration-150 enabled:active:scale-[0.97] disabled:cursor-not-allowed ${VARIANT[variant]} ${SIZE[size]} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}
