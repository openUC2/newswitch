/**
 * The auth token, and the one place it is stored.
 *
 * Deliberately framework-free. The transport layer, the websocket manager and the
 * image loaders all need the token, and they run outside React - the scoped providers
 * in `App.tsx` are even constructed at module scope, before a token could exist. So
 * nothing may capture the token at construction time: every consumer calls
 * `getToken()` at the moment it makes a request.
 *
 * `AuthProvider` mirrors this into React state via `subscribe`, which is what turns a
 * 401 into a redirect.
 */

const STORAGE_KEY = "newswitch.auth.token";

type Listener = () => void;

const listeners = new Set<Listener>();

/** Read the current token, or `null` when logged out. */
export function getToken(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    // Private-mode browsers can throw on access rather than returning null.
    return null;
  }
}

/** Persist the token and notify subscribers. */
export function setToken(token: string): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, token);
  } catch {
    // Not being able to persist is survivable; the session lasts until reload.
  }
  notify();
}

/** Drop the token and notify subscribers. Used by logout and by any 401. */
export function clearToken(): void {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Nothing to do - a token we cannot remove is one we could not store either.
  }
  notify();
}

/** Subscribe to token changes. Returns an unsubscribe function. */
export function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function notify(): void {
  listeners.forEach((listener) => {
    // One bad subscriber must not stop the others from learning about a logout.
    try {
      listener();
    } catch (error) {
      console.error("[auth] token listener failed:", error);
    }
  });
}

// `localStorage` events fire only in *other* tabs, so this is what makes logging out
// in one tab log out the rest.
if (typeof window !== "undefined") {
  window.addEventListener("storage", (event) => {
    if (event.key === STORAGE_KEY) {
      notify();
    }
  });
}
