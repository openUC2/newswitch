/** A pair of backend endpoints: HTTP API base URL and websocket URL. */
export interface BackendUrls {
  api: string;
  ws: string;
}

/**
 * Where the frontend reaches the backend.
 *
 * Per URL, the first one set wins: the one an embedding app (Electron) injects into
 * `window`, the one baked in at build time (`VITE_BACKEND_URL` / `VITE_WEBSOCKET_URL`,
 * `frontend/.env*`), or the page's own origin. The last case is the container image: it is
 * built with `vite build --mode container`, whose `.env.container` leaves both URLs empty,
 * because the backend serves the frontend itself (`backend/newswitch/routes/http/frontend.py`).
 */
export function resolveBackendUrls(
  injected: Partial<BackendUrls>,
  built: Partial<BackendUrls>,
  location: Pick<Location, "protocol" | "host" | "origin">,
): BackendUrls {
  const wsScheme = location.protocol === "https:" ? "wss:" : "ws:";
  return {
    api: injected.api || built.api || location.origin,
    ws: injected.ws || built.ws || `${wsScheme}//${location.host}/ws`,
  };
}
