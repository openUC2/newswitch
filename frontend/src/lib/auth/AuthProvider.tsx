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
import { AuthContext, InvalidCredentialsError } from "./context";
import { clearToken, getToken, setToken, subscribe } from "./token";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTokenState] = useState<string | null>(() => getToken());

  // Anything that clears the token - a 401 in authFetch, a 1008 websocket close,
  // another tab logging out - lands here and re-renders the guard.
  useEffect(() => subscribe(() => setTokenState(getToken())), []);

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

  const logout = useCallback(() => clearToken(), []);

  const value = useMemo(
    () => ({ token, isAuthenticated: token !== null, login, logout }),
    [token, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
