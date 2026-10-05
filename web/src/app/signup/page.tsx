"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { useAuth } from "@/lib/auth";

export default function SignupPage() {
  const { signup } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await signup(email, password);
      router.replace("/app");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Signup failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="relative flex min-h-dvh items-center justify-center overflow-hidden bg-canvas px-4">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 app-ambient"
      />
      <div className="relative z-10 w-full max-w-sm rounded-[18px] border border-line bg-surface/95 p-6 shadow-raised backdrop-blur">
        <Link href="/" className="flex items-center gap-2">
          <span className="flex size-7 items-center justify-center rounded-[7px] bg-accent text-[11px] font-bold text-white shadow-btn">
            6
          </span>
          <span className="text-[14px] font-semibold tracking-[-0.02em] text-ink">
            Six<span className="text-accent">Call</span>
          </span>
        </Link>
        <h1 className="mt-5 text-[24px] font-semibold tracking-[-0.03em] text-ink">
          Create account
        </h1>
        <p className="mt-1 text-[13px] text-ink-2">
          Email and password — stored in your connected Postgres.
        </p>
        <form onSubmit={onSubmit} className="mt-5 flex flex-col gap-3">
          <label className="flex flex-col gap-1.5">
            <span className="text-[12px] font-medium text-ink-2">Email</span>
            <input
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="rounded-[10px] border border-line bg-field px-3 py-2.5 text-[13px] text-ink outline-none transition focus:border-line-strong focus:shadow-[0_0_0_3px_color-mix(in_srgb,var(--accent)_12%,transparent)]"
            />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-[12px] font-medium text-ink-2">Password</span>
            <input
              type="password"
              required
              minLength={6}
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="rounded-[10px] border border-line bg-field px-3 py-2.5 text-[13px] text-ink outline-none transition focus:border-line-strong focus:shadow-[0_0_0_3px_color-mix(in_srgb,var(--accent)_12%,transparent)]"
            />
          </label>
          {error && (
            <p className="rounded-[8px] bg-red-tint px-3 py-2 text-[12.5px] text-red">
              {error}
            </p>
          )}
          <button
            type="submit"
            disabled={busy}
            className="mt-1 rounded-[10px] bg-accent py-2.5 text-[13.5px] font-semibold text-white shadow-btn transition hover:bg-accent-ink disabled:opacity-50"
          >
            {busy ? "Creating…" : "Create account"}
          </button>
        </form>
        <p className="mt-4 text-center text-[12.5px] text-ink-3">
          Already have an account?{" "}
          <Link href="/login" className="font-medium text-accent-ink">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
