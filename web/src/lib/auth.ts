"use client";

import { useCallback, useEffect, useState } from "react";
import {
  login as apiLogin,
  logout as apiLogout,
  me,
  signup as apiSignup,
  type AuthUser,
} from "@/lib/api";

const TOKEN_KEY = "sixcall_token";

export function getStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setStoredToken(token: string | null) {
  if (typeof window === "undefined") return;
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export function useAuth() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    const token = getStoredToken();
    if (!token) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      const res = await me(token);
      setUser(res.user);
    } catch {
      setStoredToken(null);
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    const token = getStoredToken();

    const applySignedOut = () => {
      if (cancelled) return;
      setUser(null);
      setLoading(false);
    };

    if (!token) {
      const t = window.setTimeout(applySignedOut, 0);
      return () => {
        cancelled = true;
        window.clearTimeout(t);
      };
    }

    me(token)
      .then((res) => {
        if (!cancelled) setUser(res.user);
      })
      .catch(() => {
        if (cancelled) return;
        setStoredToken(null);
        setUser(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const signup = useCallback(async (email: string, password: string) => {
    const res = await apiSignup(email, password);
    setStoredToken(res.token);
    setUser(res.user);
    return res.user;
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const res = await apiLogin(email, password);
    setStoredToken(res.token);
    setUser(res.user);
    return res.user;
  }, []);

  const logout = useCallback(async () => {
    const token = getStoredToken();
    if (token) {
      try {
        await apiLogout(token);
      } catch {
        /* ignore */
      }
    }
    setStoredToken(null);
    setUser(null);
  }, []);

  return { user, loading, signup, login, logout, refresh };
}
