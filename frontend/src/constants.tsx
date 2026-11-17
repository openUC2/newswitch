import { resolveBackendUrls } from "@/lib/backendUrls";

// The backend URLs: injected into the global scope by the electron app, baked in from the
// environment at build time, or - in the container image - the page's own origin.
const backendUrls = resolveBackendUrls(
  { api: window.__agent_url__, ws: window.__agent_ws_url__ },
  {
    api: import.meta.env.VITE_BACKEND_URL,
    ws: import.meta.env.VITE_WEBSOCKET_URL,
  },
  window.location,
);

export const BACKEND_API = backendUrls.api;
export const BACKEND_WS = backendUrls.ws;

export const H264_STREAM_PATH = BACKEND_API + "/stream/h264";
export const ZSTD_STREAM_PATH = BACKEND_API + "/stream/zstd";
