import { useEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { completeOIDCLogin, OIDCSignInError } from "../lib/auth/oidc";

export function OIDCCallbackPage() {
  const { search, pathname } = useLocation();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    // Remove the authorization code from the address bar before exchanging it.
    window.history.replaceState(window.history.state, "", pathname);
    void completeOIDCLogin(search)
      .then((from) => navigate(from, { replace: true }))
      .catch((error: unknown) => {
        navigate("/login", {
          replace: true,
          state: {
            oidcFailure:
              error instanceof OIDCSignInError ? error.reason : "failed",
          },
        });
      });
  }, [search, pathname, navigate]);

  return (
    <div className="dark flex min-h-screen items-center justify-center bg-background text-foreground">
      <p role="status">{t("auth.signingIn")}</p>
    </div>
  );
}
