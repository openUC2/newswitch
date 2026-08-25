/**
 * React's view of the auth token.
 *
 * The token itself lives in `token.ts`, outside React, because the transport layer
 * needs it synchronously. This provider mirrors it into state so that losing the token
 * - through logout, a 401, or a websocket closing with 1008 - re-renders the guard and
 * sends the user to the login page.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { BACKEND_API } from "@/constants";
import { AuthContext, InvalidCredentialsError, type Role } from "./context";
import { clearToken, getToken, setToken, subscribe } from "./token";

type Identity = { username: string; role: Role };

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTokenState] = useState<string | null>(() => getToken());
  const [identity, setIdentity] = useState<Identity | null>(null);

  // Anything that clears the token - a 401 in authFetch, a 1008 websocket close,
  // another tab logging out - lands here and re-renders the guard.
  useEffect(() => subscribe(() => setTokenState(getToken())), []);

  // The token says *that* someone is logged in; this fills in *who* and with what
  // role, which RequireAdmin and the account menu need but the token alone can't say.
  // Stale identity data left over after a logout is harmless: nothing reachable while
  // logged out (RequireAuth intercepts first) ever reads it.
  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    fetch(`${BACKEND_API}/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((response) =>
        response.ok ? (response.json() as Promise<Identity>) : null,
      )
      .then((data) => {
        if (!cancelled) setIdentity(data);
      })
      .catch(() => {
        if (!cancelled) setIdentity(null);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const login = useCallback(async (username: string, password: string) => {
    const response = await fetch(`${BACKEND_API}/auth/login`, {
      method: "POST",
      headers: {
        // The password is sent exactly once, here. Every later request uses the
        // token the backend hands back.
        Authorization: `Basic ${btoa(`${username}:${password}`)}`,
      },
    });

    if (response.status === 401) {
      throw new InvalidCredentialsError();
    }
    if (!response.ok) {
      throw new Error(`Login failed: ${response.status}`);
    }

    const { token: issued } = (await response.json()) as { token: string };
    setToken(issued);
  }, []);

  const logout = useCallback(() => {
    const activeToken = getToken();
    // Best-effort: the client logs out regardless of whether the backend can be
    // reached, so a dropped connection never traps the user behind a stuck session.
    void fetch(`${BACKEND_API}/auth/logout`, {
      method: "POST",
      headers: activeToken ? { Authorization: `Bearer ${activeToken}` } : {},
    }).catch(() => {});
    clearToken();
  }, []);

  const value = useMemo(
    () => ({
      token,
      isAuthenticated: token !== null,
      username: identity?.username ?? null,
      role: identity?.role ?? null,
      login,
      logout,
    }),
    [token, identity, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
