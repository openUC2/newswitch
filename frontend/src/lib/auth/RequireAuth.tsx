/**
 * The route guard.
 *
 * Rendering `<Outlet/>` only when a token exists means the expensive providers below
 * it - the transport, its websocket, the state stores - are never mounted for a logged
 * -out user, so no unauthenticated request is made in the first place.
 */

import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "./context";

export function RequireAuth() {
  const { isAuthenticated } = useAuth();
  const location = useLocation();

  if (!isAuthenticated) {
    // `state.from` lets the login page send the user back where they were headed,
    // which matters on a reload of a deep link or after a token expires mid-session.
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return <Outlet />;
}
