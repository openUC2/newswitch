import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  completeOIDCFlow,
  confirmOIDCLink,
  OIDCLinkError,
  oidcLinkErrorMessages,
  oidcReturnPath,
  OIDCSignInError,
  takeOIDCAttempt,
  type OIDCLinkPreview,
} from "../lib/auth/oidc";

export function OIDCCallbackPage() {
  const { search, pathname } = useLocation();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const started = useRef(false);
  const [link, setLink] = useState<{
    from: string;
    preview: OIDCLinkPreview | null;
  } | null>(null);
  const [linkError, setLinkError] = useState<
    keyof typeof oidcLinkErrorMessages | null
  >(null);
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    // Remove the authorization code from the address bar before exchanging it.
    window.history.replaceState(window.history.state, "", pathname);
    const attempt = takeOIDCAttempt();
    const from = oidcReturnPath(attempt?.from);
    void completeOIDCFlow(search, attempt)
      .then((preview) => {
        if (preview) setLink({ from, preview });
        else navigate(from, { replace: true });
      })
      .catch((error: unknown) => {
        if (attempt?.link) {
          setLink({ from, preview: null });
          setLinkError(
            error instanceof OIDCLinkError ? error.reason : "failed",
          );
          return;
        }
        navigate("/login", {
          replace: true,
          state: {
            oidcFailure:
              error instanceof OIDCSignInError ? error.reason : "failed",
          },
        });
      });
  }, [search, pathname, navigate]);

  const confirm = async () => {
    if (!link?.preview) return;
    setConfirming(true);
    setLinkError(null);
    try {
      await confirmOIDCLink(link.preview.ticket);
      toast.success(t("auth.openUC2LinkSuccess"));
      navigate(link.from, { replace: true });
    } catch (error) {
      setLinkError(error instanceof OIDCLinkError ? error.reason : "failed");
    } finally {
      setConfirming(false);
    }
  };

  return (
    <div className="dark flex min-h-screen items-center justify-center bg-background p-4 text-foreground">
      {link ? (
        <Card className="w-full max-w-md">
          <CardHeader>
            <CardTitle>{t("auth.linkOpenUC2")}</CardTitle>
            {link.preview && (
              <CardDescription>
                {t("auth.openUC2LinkConfirmDescription")}
              </CardDescription>
            )}
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            {link.preview && (
              <dl className="grid gap-3 rounded-md border p-3 text-sm">
                <div>
                  <dt className="text-muted-foreground">
                    {t("auth.localAccount")}
                  </dt>
                  <dd className="break-all font-medium">
                    {link.preview.local_username}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">
                    {t("auth.openUC2Account")}
                  </dt>
                  <dd className="break-all font-medium">
                    {link.preview.account_name}
                  </dd>
                </div>
              </dl>
            )}
            {linkError && (
              <p role="alert" className="text-sm text-destructive">
                {t(oidcLinkErrorMessages[linkError])}
              </p>
            )}
            <div className="flex flex-wrap justify-end gap-2">
              <Button
                variant="outline"
                disabled={confirming}
                onClick={() => navigate(link.from, { replace: true })}
              >
                {link.preview ? t("common.cancel") : t("common.close")}
              </Button>
              {link.preview && (
                <Button onClick={confirm} disabled={confirming}>
                  {t("auth.openUC2LinkConfirm")}
                </Button>
              )}
            </div>
          </CardContent>
        </Card>
      ) : (
        <p role="status">{t("auth.signingIn")}</p>
      )}
    </div>
  );
}
