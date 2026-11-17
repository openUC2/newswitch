import { describe, expect, it } from "vitest";
import { resolveBackendUrls } from "./backendUrls";

const PAGE = {
  protocol: "http:",
  host: "openuc2.local:8069",
  origin: "http://openuc2.local:8069",
};

describe("resolveBackendUrls", () => {
  it("prefers the URLs an embedding app injects", () => {
    const urls = resolveBackendUrls(
      { api: "http://agent:1", ws: "ws://agent:1/ws" },
      { api: "http://localhost:8069", ws: "ws://localhost:8069/ws" },
      PAGE,
    );
    expect(urls).toEqual({ api: "http://agent:1", ws: "ws://agent:1/ws" });
  });

  it("uses the URLs baked in at build time (just dev)", () => {
    const urls = resolveBackendUrls(
      {},
      { api: "http://localhost:8069", ws: "ws://localhost:8069/ws" },
      PAGE,
    );
    expect(urls).toEqual({
      api: "http://localhost:8069",
      ws: "ws://localhost:8069/ws",
    });
  });

  it("falls back to the page's own origin when the build leaves them empty (container)", () => {
    const urls = resolveBackendUrls({}, { api: "", ws: "" }, PAGE);
    expect(urls).toEqual({
      api: "http://openuc2.local:8069",
      ws: "ws://openuc2.local:8069/ws",
    });
  });

  it("uses a secure websocket on an https page", () => {
    const urls = resolveBackendUrls(
      {},
      {},
      { protocol: "https:", host: "scope.lab", origin: "https://scope.lab" },
    );
    expect(urls.ws).toBe("wss://scope.lab/ws");
  });
});
