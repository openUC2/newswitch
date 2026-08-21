import { beforeEach, describe, expect, it, vi } from "vitest";
import { authFetch, withToken } from "./authFetch";
import { clearToken, getToken, setToken, subscribe } from "./token";

const TOKEN = "abc123";

beforeEach(() => {
  window.localStorage.clear();
  vi.restoreAllMocks();
});

describe("token store", () => {
  it("round-trips a token", () => {
    expect(getToken()).toBeNull();
    setToken(TOKEN);
    expect(getToken()).toBe(TOKEN);
    clearToken();
    expect(getToken()).toBeNull();
  });

  it("survives a reload", () => {
    setToken(TOKEN);
    // A fresh read is what a page load does; the value must come from storage
    // rather than from module state.
    expect(window.localStorage.getItem("newswitch.auth.token")).toBe(TOKEN);
  });

  it("notifies subscribers, which is what turns a 401 into a redirect", () => {
    const listener = vi.fn();
    const unsubscribe = subscribe(listener);

    setToken(TOKEN);
    expect(listener).toHaveBeenCalledTimes(1);

    clearToken();
    expect(listener).toHaveBeenCalledTimes(2);

    unsubscribe();
    setToken(TOKEN);
    expect(listener).toHaveBeenCalledTimes(2);
  });

  it("keeps notifying after a subscriber throws", () => {
    const good = vi.fn();
    vi.spyOn(console, "error").mockImplementation(() => {});
    // Both are unsubscribed at the end: the listener set is module-level, so a
    // leaked throwing subscriber would spray errors through every later test.
    const unsubscribeBad = subscribe(() => {
      throw new Error("boom");
    });
    const unsubscribeGood = subscribe(good);

    setToken(TOKEN);
    expect(good).toHaveBeenCalled();

    unsubscribeBad();
    unsubscribeGood();
  });
});

describe("withToken", () => {
  it("appends the token for callers that cannot set headers", () => {
    setToken(TOKEN);
    expect(withToken("http://localhost:8099/files/a.png")).toBe(
      `http://localhost:8099/files/a.png?token=${TOKEN}`,
    );
  });

  it("preserves an existing query string", () => {
    setToken(TOKEN);
    const url = new URL(withToken("http://localhost:8099/cache/f1?scale=2"));
    expect(url.searchParams.get("scale")).toBe("2");
    expect(url.searchParams.get("token")).toBe(TOKEN);
  });

  it("leaves the URL alone when logged out", () => {
    // Better a clean 401 than a URL carrying `token=null`.
    expect(withToken("http://localhost:8099/files/a.png")).toBe(
      "http://localhost:8099/files/a.png",
    );
  });

  it("survives zarrita resolving a chunk against it", () => {
    // zarrita builds each chunk URL with `new URL(path, base)`, which drops the
    // base's query string, then copies `base.search` back on. This asserts the
    // property that behaviour relies on: the token must be in `search`.
    setToken(TOKEN);
    const base = new URL(withToken("http://localhost:8099/cache/f1"));
    base.pathname += "/";
    const resolved = new URL("zarr.json", base);
    resolved.search = base.search;

    expect(resolved.searchParams.get("token")).toBe(TOKEN);
    expect(resolved.pathname).toBe("/cache/f1/zarr.json");
  });
});

describe("authFetch", () => {
  it("sends the bearer token", async () => {
    setToken(TOKEN);
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response("{}", { status: 200 }));

    await authFetch("http://localhost:8099/states");

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect((init.headers as Record<string, string>).Authorization).toBe(
      `Bearer ${TOKEN}`,
    );
  });

  it("keeps caller headers", async () => {
    setToken(TOKEN);
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response("{}", { status: 200 }));

    await authFetch("http://localhost:8099/states", {
      headers: { "Content-Type": "application/json" },
    });

    const headers = (fetchMock.mock.calls[0][1] as RequestInit)
      .headers as Record<string, string>;
    expect(headers["Content-Type"]).toBe("application/json");
    expect(headers.Authorization).toBe(`Bearer ${TOKEN}`);
  });

  it("clears the token on a 401 so the guard can redirect", async () => {
    setToken(TOKEN);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("{}", { status: 401 }),
    );

    await authFetch("http://localhost:8099/states");

    expect(getToken()).toBeNull();
  });

  it("keeps the token on an unrelated error", async () => {
    // A 500 is the backend's problem, not a reason to log the user out.
    setToken(TOKEN);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("{}", { status: 500 }),
    );

    await authFetch("http://localhost:8099/states");

    expect(getToken()).toBe(TOKEN);
  });
});
