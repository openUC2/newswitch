/**
 * The guard has to do more than hide the UI.
 *
 * Below it sit the transport and its websocket, and the server authenticated that
 * socket once, from the init frame - it has no idea the token was dropped afterwards.
 * So if the guard left the subtree mounted, a logged-out browser would keep streaming
 * live microscope state in the background. These tests pin the chain that prevents
 * that: clearing the token unmounts the subtree, and TransportProvider's cleanup
 * effect (`subscriptionManager.dispose`) closes the sockets on unmount.
 *
 * Uses react-dom directly rather than @testing-library/react, whose
 * @testing-library/dom peer is not installed in this project.
 */

import { act, useEffect } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "./AuthProvider";
import { RequireAuth } from "./RequireAuth";
import { clearToken, setToken } from "./token";

// Tells React that act() may flush effects here; without it React warns and does not
// guarantee that the unmount we assert on has actually run.
(
  globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
).IS_REACT_ACT_ENVIRONMENT = true;

const TOKEN = "abc123";

let container: HTMLDivElement;
let root: Root;

/** Stands in for the provider tree that owns the websocket. */
function SocketOwner({ onUnmount }: { onUnmount: () => void }) {
  useEffect(() => onUnmount, [onUnmount]);
  return <div>protected</div>;
}

function renderApp(onUnmount: () => void) {
  act(() => {
    root.render(
      <MemoryRouter initialEntries={["/"]}>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<div>login</div>} />
            <Route element={<RequireAuth />}>
              <Route path="/" element={<SocketOwner onUnmount={onUnmount} />} />
            </Route>
          </Routes>
        </AuthProvider>
      </MemoryRouter>,
    );
  });
}

const text = () => container.textContent ?? "";

beforeEach(() => {
  window.localStorage.clear();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("RequireAuth", () => {
  it("sends a logged-out visitor to the login page", () => {
    renderApp(() => {});
    expect(text()).toContain("login");
  });

  it("never mounts the protected subtree while logged out", () => {
    // The strongest form of "makes no unauthenticated requests": the code that
    // would make them is never rendered.
    const onUnmount = vi.fn();
    renderApp(onUnmount);
    expect(text()).not.toContain("protected");
    expect(onUnmount).not.toHaveBeenCalled();
  });

  it("renders the protected subtree once a token exists", () => {
    setToken(TOKEN);
    renderApp(() => {});
    expect(text()).toContain("protected");
  });

  it("unmounts the socket-owning subtree when the token is cleared", () => {
    // This is the one that matters: logout, a 401, and a 1008 websocket close all
    // funnel into clearToken, and each must tear the transport down rather than
    // leave a server-side-authenticated socket streaming to a logged-out page.
    setToken(TOKEN);
    const onUnmount = vi.fn();
    renderApp(onUnmount);
    expect(text()).toContain("protected");

    act(() => clearToken());

    expect(onUnmount).toHaveBeenCalledTimes(1);
    expect(text()).not.toContain("protected");
    expect(text()).toContain("login");
  });
});
