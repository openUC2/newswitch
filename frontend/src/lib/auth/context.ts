/**
 * The auth context and its hook, kept apart from the provider component so that
 * `AuthProvider.tsx` exports only a component and stays fast-refresh friendly (the
 * same split as `panelContext.ts` / `PanelProvider.tsx`).
 */

import { createContext, useContext } from "react";

export type AuthContextValue = {
  token: string | null;
  isAuthenticated: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
};

export const AuthContext = createContext<AuthContextValue | null>(null);

/** Thrown when the backend rejects the credentials, as opposed to being unreachable. */
export class InvalidCredentialsError extends Error {
  constructor() {
    super("Invalid username or password");
    this.name = "InvalidCredentialsError";
  }
}

/** Access the auth context. Throws outside an `AuthProvider`. */
export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
