/**
 * Route guard for admin-only pages (user/role management, the audit log).
 *
 * Layered inside `RequireAuth`: by the time this runs, a token already exists, so the
 * only question left is the role `AuthProvider` fetched from `/auth/me`.
 */

import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "./context";

export function RequireAdmin() {
  const { role } = useAuth();

  if (role !== "admin") {
    return <Navigate to="/" replace />;
  }

  return <Outlet />;
}
