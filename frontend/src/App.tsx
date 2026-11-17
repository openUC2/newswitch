import "./App.css";
import type { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { Toaster } from "./components/ui/sonner";
import { AppNavigationChrome } from "./components/navigation/AppNavigationChrome";
import { createScopedProvider } from "./lib/rekuest";
import { AuthProvider } from "./lib/auth/AuthProvider";
import { RequireAuth } from "./lib/auth/RequireAuth";
import { RequireAdmin } from "./lib/auth/RequireAdmin";
import {
  AuditLogPage,
  IndexPage,
  LoginPage,
  ReplayPage,
  UsersPage,
} from "./pages";
import { appsDefinition } from "./apps";
import { LocalStoreProvider } from "./store";
import { BACKEND_API, BACKEND_WS } from "./constants";

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

          {/* Admin-only, and deliberately outside ScopedRoute: managing accounts
              should not depend on the microscope backend connection at all. */}
          <Route element={<RequireAdmin />}>
            <Route path="/admin/users" element={<UsersPage />} />
            <Route path="/admin/audit" element={<AuditLogPage />} />
          </Route>
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <Toaster position="bottom-right" richColors />
    </AuthProvider>
  );
}

export default App;
