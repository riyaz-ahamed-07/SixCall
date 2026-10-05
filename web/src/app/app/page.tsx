"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import AgentShell from "@/components/shell/AgentShell";
import { useAuth } from "@/lib/auth";

export default function AppPage() {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  if (loading) {
    return (
      <div className="flex h-dvh items-center justify-center bg-canvas text-[13px] text-ink-2">
        Checking session…
      </div>
    );
  }
  if (!user) return null;
  return <AgentShell userEmail={user.email} />;
}
