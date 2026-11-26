import { BACKEND_API } from "@/constants";
import { setToken } from "./token";

const LOGIN_KEY = "newswitch-oidc-login";

type LoginAttempt = { state: string; proof: string; from: string };
export type OIDCFailure = "unlinked" | "unavailable" | "failed";

export class OIDCSignInError extends Error {
  readonly reason: OIDCFailure;

  constructor(reason: OIDCFailure) {
    super(reason);
    this.reason = reason;
  }
}

export async function getOIDCIssuer(
  signal: AbortSignal,
): Promise<string | null> {
  const response = await fetch(`${BACKEND_API}/auth/oidc/enabled`, {
    signal,
    cache: "no-store",
  });
  if (!response.ok) throw new OIDCSignInError("unavailable");
  const { enabled, issuer } = await response.json();
  return enabled === true && typeof issuer === "string" ? issuer : null;
}

export async function oidcIsReachable(
  issuer: string,
  signal: AbortSignal,
): Promise<boolean> {
  // The browser follows the login redirect; the instrument exchanges the code.
  const [backend, provider] = await Promise.all([
    fetch(`${BACKEND_API}/auth/oidc/availability`, {
      signal,
      cache: "no-store",
    }),
    fetch(`${issuer}/.well-known/openid-configuration`, {
      signal,
      cache: "no-store",
      credentials: "omit",
    }),
  ]);
  return (
    backend.ok &&
    provider.ok &&
    (await backend.json()).available === true &&
    (await provider.json()).issuer === issuer
  );
}

export async function startOIDCLogin(from: string): Promise<void> {
  const response = await fetch(`${BACKEND_API}/auth/oidc/start`, {
    method: "POST",
  });
  if (!response.ok) throw new OIDCSignInError("unavailable");
  const { authorization_url, state, proof } = (await response.json()) as {
    authorization_url: string;
    state: string;
    proof: string;
  };
  sessionStorage.setItem(LOGIN_KEY, JSON.stringify({ state, proof, from }));
  window.location.assign(authorization_url);
}

export async function completeOIDCLogin(search: string): Promise<string> {
  const saved = sessionStorage.getItem(LOGIN_KEY);
  sessionStorage.removeItem(LOGIN_KEY);

  const params = new URLSearchParams(search);
  const code = params.get("code");
  const state = params.get("state");
  const attempt = saved ? (JSON.parse(saved) as LoginAttempt) : null;
  if (!code || !state || !attempt || state !== attempt.state) {
    throw new OIDCSignInError("failed");
  }

  const response = await fetch(`${BACKEND_API}/auth/oidc/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code, state, proof: attempt.proof }),
  });
  if (response.status === 403) throw new OIDCSignInError("unlinked");
  if (response.status === 503) throw new OIDCSignInError("unavailable");
  if (!response.ok) throw new OIDCSignInError("failed");

  const { token } = (await response.json()) as { token: string };
  setToken(token);
  const target = new URL(attempt.from, window.location.origin);
  return target.origin === window.location.origin
    ? target.pathname + target.search + target.hash
    : "/";
}
