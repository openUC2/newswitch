import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useLocation } from "react-router-dom";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  OIDCLinkError,
  oidcLinkErrorMessages,
  oidcLinkStatus,
  startOIDCLink,
} from "@/lib/auth/oidc";

export function LinkOpenUC2Dialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const location = useLocation();
  const [status, setStatus] = useState<
    "loading" | "unlinked" | "linked" | "failed"
  >("loading");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<keyof typeof oidcLinkErrorMessages | null>(
    null,
  );
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    void oidcLinkStatus(controller.signal)
      .then((linked) => setStatus(linked ? "linked" : "unlinked"))
      .catch(() => {
        if (!controller.signal.aborted) setStatus("failed");
      });
    return () => controller.abort();
  }, []);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await startOIDCLink(
        password,
        location.pathname + location.search + location.hash,
      );
    } catch (caught) {
      setError(caught instanceof OIDCLinkError ? caught.reason : "failed");
      setSubmitting(false);
    }
  };

  return (
    <Dialog open onOpenChange={(open) => !open && !submitting && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("auth.linkOpenUC2")}</DialogTitle>
          <DialogDescription>
            {t(
              status === "linked"
                ? "auth.openUC2AlreadyLinked"
                : "auth.openUC2LinkDescription",
            )}
          </DialogDescription>
        </DialogHeader>
        {status === "loading" && <p role="status">{t("common.loading")}</p>}
        {status === "failed" && (
          <p role="alert" className="text-sm text-destructive">
            {t("auth.openUC2LinkFailed")}
          </p>
        )}
        {status === "unlinked" && (
          <form onSubmit={submit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="link-local-password">
                {t("auth.currentPassword")}
              </Label>
              <Input
                id="link-local-password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
            </div>
            {error && (
              <p role="alert" className="text-sm text-destructive">
                {t(oidcLinkErrorMessages[error])}
              </p>
            )}
            <DialogFooter>
              <Button type="submit" disabled={submitting || !password}>
                {t("auth.keycloakSignIn")}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
