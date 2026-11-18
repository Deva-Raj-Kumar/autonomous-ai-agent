"use client";
// Who is logged in, shared with every page through React context.
//
// On first load: try the refresh cookie ("silent login"). If it works, the user stays
// logged in across reloads WITHOUT any token in localStorage.

import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import * as api from "@/lib/api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const router = useRouter();
  const [user, setUser] = useState(null);
  const [status, setStatus] = useState("loading"); // loading | authenticated | anonymous

  const loadUser = useCallback(async () => {
    const me = await api.apiFetch("/auth/me");
    setUser(me);
    setStatus("authenticated");
    return me;
  }, []);

  useEffect(() => {
    api.onSessionExpired(() => {
      setUser(null);
      setStatus("anonymous");
    });
    let cancelled = false;
    (async () => {
      try {
        if (await api.refreshAccessToken()) {
          if (!cancelled) await loadUser();
          return;
        }
      } catch {
        // backend unreachable: treat as logged out
      }
      if (!cancelled) setStatus("anonymous");
    })();
    return () => {
      cancelled = true;
    };
  }, [loadUser]);

  const login = useCallback(async (email, password) => {
    await api.login(email, password);
    return loadUser();
  }, [loadUser]);

  const logout = useCallback(async () => {
    await api.logout();
    setUser(null);
    setStatus("anonymous");
    router.replace("/login");
  }, [router]);

  const loginWithGoogle = useCallback(async (email = null, username = null) => {
    await api.googleLogin(email, username);
    return loadUser();
  }, [loadUser]);

  const resetUserPassword = useCallback(async (email, newPassword) => {
    await api.resetPassword(email, newPassword);
    return loadUser();
  }, [loadUser]);

  const value = useMemo(
    () => ({ user, status, login, logout, loginWithGoogle, resetUserPassword }),
    [user, status, login, logout, loginWithGoogle, resetUserPassword]
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth() must be used inside <AuthProvider>");
  return value;
}

/**
 * Where to go after login. Only same-site paths: "?next=https://evil.example" or
 * "?next=//evil.example" would turn our login page into an OPEN REDIRECT (a phishing
 * tool that starts on our real domain).
 */
export function safeNextPath(next) {
  if (typeof next !== "string" || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) {
    return "/";
  }
  return next;
}
