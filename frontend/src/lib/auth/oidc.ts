import { BACKEND_API } from "@/constants";
import { authFetch } from "./authFetch";
import { setToken } from "./token";

const LOGIN_KEY = "newswitch-oidc-login";

type LoginAttempt = { state: string; proof: string; from: string; link?: true };
export type OIDCLinkPreview = {
  ticket: string;
  local_username: string;
  account_name: string;
};
export type OIDCFailure = "unlinked" | "unavailable" | "failed";

export class OIDCSignInError extends Error {
  readonly reason: OIDCFailure;

  constructor(reason: OIDCFailure) {
    super(reason);
    this.reason = reason;
  }
}

export const oidcLinkErrorMessages = {
  password: "auth.currentPasswordIncorrect",
  conflict: "auth.openUC2LinkConflict",
  unavailable: "auth.keycloakUnavailable",
  failed: "auth.openUC2LinkFailed",
} as const;

export class OIDCLinkError extends Error {
  readonly reason: keyof typeof oidcLinkErrorMessages;

  constructor(reason: keyof typeof oidcLinkErrorMessages) {
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
  await followOIDCRedirect(response, from);
}

export async function oidcLinkStatus(signal: AbortSignal): Promise<boolean> {
  const response = await authFetch(`${BACKEND_API}/auth/oidc/link`, {
    signal,
    cache: "no-store",
  });
  if (!response.ok) throw new OIDCLinkError("failed");
  return (await response.json()).linked === true;
}

export async function startOIDCLink(
  currentPassword: string,
  from: string,
): Promise<void> {
  const response = await authFetch(`${BACKEND_API}/auth/oidc/link/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ current_password: currentPassword }),
  });
  if (response.status === 403) throw new OIDCLinkError("password");
  if (response.status === 409) throw new OIDCLinkError("conflict");
  if (response.status === 503) throw new OIDCLinkError("unavailable");
  if (!response.ok) throw new OIDCLinkError("failed");
  await followOIDCRedirect(response, from, true);
}

async function followOIDCRedirect(
  response: Response,
  from: string,
  link?: true,
): Promise<void> {
  const { authorization_url, state, proof } = (await response.json()) as {
    authorization_url: string;
    state: string;
    proof: string;
  };
  sessionStorage.setItem(
    LOGIN_KEY,
    JSON.stringify({ state, proof, from, link }),
  );
  window.location.assign(authorization_url);
}

export function takeOIDCAttempt(): LoginAttempt | null {
  try {
    const saved = sessionStorage.getItem(LOGIN_KEY);
    sessionStorage.removeItem(LOGIN_KEY);
    return saved ? (JSON.parse(saved) as LoginAttempt) : null;
  } catch {
    return null;
  }
}

export async function completeOIDCFlow(
  search: string,
  attempt: LoginAttempt | null,
): Promise<OIDCLinkPreview | null> {
  const params = new URLSearchParams(search);
  const code = params.get("code");
  const state = params.get("state");
  if (!code || !state || !attempt || state !== attempt.state) {
    throw new OIDCSignInError("failed");
  }

  const init: RequestInit = {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code, state, proof: attempt.proof }),
  };
  if (attempt.link) {
    const response = await authFetch(
      `${BACKEND_API}/auth/oidc/link/preview`,
      init,
    );
    if (response.status === 503) throw new OIDCLinkError("unavailable");
    if (!response.ok) throw new OIDCLinkError("failed");
    return (await response.json()) as OIDCLinkPreview;
  }

  const response = await fetch(`${BACKEND_API}/auth/oidc/complete`, init);
  if (response.status === 403) throw new OIDCSignInError("unlinked");
  if (response.status === 503) throw new OIDCSignInError("unavailable");
  if (!response.ok) throw new OIDCSignInError("failed");

  const { token } = (await response.json()) as { token: string };
  setToken(token);
  return null;
}

export async function confirmOIDCLink(ticket: string): Promise<void> {
  const response = await authFetch(`${BACKEND_API}/auth/oidc/link/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ticket }),
  });
  if (response.status === 409) throw new OIDCLinkError("conflict");
  if (!response.ok) throw new OIDCLinkError("failed");
}

export function oidcReturnPath(from = "/"): string {
  try {
    const target = new URL(from, window.location.origin);
    if (
      target.origin === window.location.origin &&
      !target.pathname.startsWith("//")
    ) {
      return target.pathname + target.search + target.hash;
    }
  } catch {
    // Resume at the instrument home if the previous route is no longer usable.
  }
  return "/";
}
