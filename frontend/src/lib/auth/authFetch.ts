/**
 * Attaching the token to outbound requests.
 *
 * Three shapes, because the browser only lets some callers set headers:
 *
 * - `authFetch` for anything that goes through `fetch`.
 * - `withToken` for URLs handed to a loader that sets its own headers - three.js'
 *   `TextureLoader` and zarrita's fetch store. The token lands in the query string,
 *   which is why it is a one-way hash of the password rather than the password itself.
 * - `authFrame` for websockets, which cannot set headers at all and instead send the
 *   token in their first message.
 */

import { clearToken, getToken } from "./token";

/** `fetch` with the bearer token attached, clearing the token on a 401. */
export async function authFetch(
  input: RequestInfo | URL,
  init: RequestInit = {},
): Promise<Response> {
  const token = getToken();

  const response = await fetch(input, {
    ...init,
    headers: {
      ...init.headers,
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });

  if (response.status === 401) {
    // Only clear the token. Navigation is left to AuthProvider, which is inside the
    // router and can redirect properly; calling a navigate hook from here would tie
    // the transport layer to React's render cycle.
    clearToken();
  }

  return response;
}

/**
 * Append the token to a URL, for callers that cannot set a header.
 *
 * Returns the URL unchanged when logged out, so the request fails as a clean 401
 * rather than as a malformed URL.
 */
export function withToken(url: string): string {
  const token = getToken();
  if (!token) return url;

  const parsed = new URL(url, window.location.origin);
  parsed.searchParams.set("token", token);
  return parsed.toString();
}

/** The opening frame a websocket sends to authenticate itself. */
export function authFrame(): { type: "auth"; token: string | null } {
  return { type: "auth", token: getToken() };
}

/** The close code the backend uses to reject a websocket for bad credentials. */
export const WS_UNAUTHORIZED_CLOSE_CODE = 1008;
