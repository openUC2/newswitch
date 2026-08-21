import "./App.css";
import type { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { Toaster } from "./components/ui/sonner";
import { AppNavigationChrome } from "./components/navigation/AppNavigationChrome";
import { createScopedProvider } from "./lib/rekuest";
import { AuthProvider } from "./lib/auth/AuthProvider";
import { RequireAuth } from "./lib/auth/RequireAuth";
import { IndexPage, LoginPage, ReplayPage } from "./pages";
import { appsDefinition } from "./apps";
import { LocalStoreProvider } from "./store";

// The backend API URL is either injected into the global scope by the
// electron app or taken from environment variables, allowing for flexibility in different deployment scenarios.
const BACKEND_API = window.__agent_url__ || import.meta.env.VITE_BACKEND_URL;
const BACKEND_WS =
  window.__agent_ws_url__ || import.meta.env.VITE_WEBSOCKET_URL;

const ScopedAppsProvider = createScopedProvider({
  definition: appsDefinition,
  config: {
    default: {
      apiEndpoint: BACKEND_API,
      wsEndpoint: BACKEND_WS,
    },
  },
  debug: true,
  instanceId: "microscope-control-panel",
});

function ScopedRoute({
  children,
  scope,
}: {
  children: ReactNode;
  scope: string;
}) {
  return (
    <ScopedAppsProvider scope={scope}>
      <LocalStoreProvider scope={scope}>
        <AppNavigationChrome>{children}</AppNavigationChrome>
      </LocalStoreProvider>
    </ScopedAppsProvider>
  );
}

function App() {
  return (
    // AuthProvider sits inside the router (see main.tsx) so losing the token can
    // redirect, and outside <Routes> so every route shares one auth state.
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />

        {/* Everything below the guard only mounts once a token exists, so the
            transport and its websocket never connect while logged out. */}
        <Route element={<RequireAuth />}>
          <Route
            path="/"
            element={
              <ScopedRoute scope="index">
                <IndexPage />
              </ScopedRoute>
            }
          />
          <Route
            path="/replay"
            element={
              <ScopedRoute scope="replay">
                <ReplayPage />
              </ScopedRoute>
            }
          />
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <Toaster position="bottom-right" richColors />
    </AuthProvider>
  );
}

export default App;
