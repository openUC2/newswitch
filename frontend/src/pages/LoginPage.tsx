import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { z } from "zod";
import { useTranslation } from "react-i18next";
import { Globe, Monitor } from "lucide-react";
import { LanguageMenu } from "../components/navigation/LanguageMenu";
import { Button } from "../components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../components/ui/card";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "../components/ui/form";
import { Input } from "../components/ui/input";
import { InvalidCredentialsError, useAuth } from "../lib/auth/context";
import {
  getOIDCIssuer,
  oidcIsReachable,
  startOIDCLogin,
  type OIDCFailure,
} from "../lib/auth/oidc";

type LoginValues = { username: string; password: string };
type LoginLocation = { from?: Location; oidcFailure?: OIDCFailure };
type OnlineLoginStatus = "hidden" | "checking" | "available" | "unavailable";
const STATUS_POLL_INTERVAL_MS = 10_000;
const STATUS_TIMEOUT_MS = 4_000;
const oidcErrors = {
  unlinked: "auth.keycloakUnlinked",
  unavailable: "auth.keycloakUnavailable",
  failed: "auth.keycloakFailed",
} as const;

export function LoginPage() {
  const { isAuthenticated, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useTranslation();
  const loginLocation = location.state as LoginLocation | null;
  const [localError, setLocalError] = useState<
    "auth.invalidCredentials" | "auth.backendUnavailable" | null
  >(null);
  const [oidcFailure, setOIDCFailure] = useState<OIDCFailure | null>(
    () => loginLocation?.oidcFailure ?? null,
  );
  const [onlineStatus, setOnlineStatus] = useState<OnlineLoginStatus>("hidden");
  const [startingOnlineLogin, setStartingOnlineLogin] = useState(false);

  useEffect(() => {
    let pending: AbortController | null = null;
    let disposed = false;

    const refresh = async () => {
      if (pending || document.hidden) return;
      const controller = new AbortController();
      pending = controller;
      const timeout = window.setTimeout(
        () => controller.abort(),
        STATUS_TIMEOUT_MS,
      );

      try {
        const issuer = await getOIDCIssuer(controller.signal);
        if (disposed) return;
        if (!issuer) {
          setOnlineStatus("hidden");
          return;
        }
        setOnlineStatus((status) =>
          status === "hidden" ? "checking" : status,
        );
        const reachable = await oidcIsReachable(issuer, controller.signal);
        if (!disposed) setOnlineStatus(reachable ? "available" : "unavailable");
      } catch {
        if (!disposed) {
          setOnlineStatus((status) =>
            status === "hidden" ? status : "unavailable",
          );
        }
      } finally {
        window.clearTimeout(timeout);
        pending = null;
      }
    };

    void refresh();
    const interval = window.setInterval(refresh, STATUS_POLL_INTERVAL_MS);
    document.addEventListener("visibilitychange", refresh);
    window.addEventListener("online", refresh);
    window.addEventListener("offline", refresh);
    return () => {
      disposed = true;
      pending?.abort();
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", refresh);
      window.removeEventListener("online", refresh);
      window.removeEventListener("offline", refresh);
    };
  }, []);

  const loginSchema = z.object({
    username: z.string().min(1, t("auth.enterUsername")),
    password: z.string().min(1, t("auth.enterPassword")),
  });

  const form = useForm<LoginValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { username: "", password: "" },
  });

  // Where the guard bounced the user from, so a deep link survives logging in.
  const from = loginLocation?.from?.pathname ?? "/";

  if (isAuthenticated) {
    return <Navigate to={from} replace />;
  }

  const onSubmit = async (values: LoginValues) => {
    setLocalError(null);
    try {
      await login(values.username, values.password);
      navigate(from, { replace: true });
    } catch (caught) {
      setLocalError(
        caught instanceof InvalidCredentialsError
          ? "auth.invalidCredentials"
          : "auth.backendUnavailable",
      );
    }
  };

  const onOnlineLogin = async () => {
    setOIDCFailure(null);
    setStartingOnlineLogin(true);
    try {
      await startOIDCLogin(from);
    } catch {
      setOnlineStatus("unavailable");
      setStartingOnlineLogin(false);
    }
  };

  const showOnlineLogin = onlineStatus !== "hidden";
  const onlineNotice =
    onlineStatus === "checking"
      ? t("auth.checkingOnlineSignIn")
      : onlineStatus === "unavailable"
        ? t("auth.keycloakUnavailable")
        : null;
  const onlineError =
    oidcFailure &&
    (oidcFailure !== "unavailable" || onlineStatus !== "unavailable")
      ? t(oidcErrors[oidcFailure])
      : null;

  return (
    <div className="dark flex min-h-screen items-center justify-center bg-background p-4 text-foreground">
      <LanguageMenu className="fixed right-3 top-3" />
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>{t("common.appName")}</CardTitle>
          <CardDescription>{t("auth.signInDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <Form {...form}>
            <form
              onSubmit={form.handleSubmit(onSubmit)}
              className="flex flex-col gap-4"
              aria-labelledby={
                showOnlineLogin ? "local-sign-in-heading" : undefined
              }
            >
              {showOnlineLogin && (
                <h2
                  id="local-sign-in-heading"
                  className="flex items-center gap-2 text-sm font-semibold"
                >
                  <Monitor
                    className="size-4 text-muted-foreground"
                    aria-hidden="true"
                  />
                  {t("auth.localSignIn")}
                </h2>
              )}
              <FormField
                control={form.control}
                name="username"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{t("auth.username")}</FormLabel>
                    <FormControl>
                      <Input autoComplete="username" autoFocus {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="password"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{t("auth.password")}</FormLabel>
                    <FormControl>
                      <Input
                        type="password"
                        autoComplete="current-password"
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {localError && (
                <p role="alert" className="text-sm text-destructive">
                  {t(localError)}
                </p>
              )}

              <Button
                type="submit"
                disabled={form.formState.isSubmitting || startingOnlineLogin}
              >
                {form.formState.isSubmitting
                  ? t("auth.signingIn")
                  : t("auth.signIn")}
              </Button>
            </form>
          </Form>
          {showOnlineLogin && (
            <section
              aria-labelledby="online-sign-in-heading"
              className="flex flex-col gap-3 border-t border-border pt-4"
            >
              <h2
                id="online-sign-in-heading"
                className="flex items-center gap-2 text-sm font-semibold"
              >
                <Globe
                  className="size-4 text-muted-foreground"
                  aria-hidden="true"
                />
                {t("auth.onlineSignIn")}
              </h2>
              <Button
                type="button"
                variant="outline"
                disabled={
                  onlineStatus !== "available" ||
                  startingOnlineLogin ||
                  form.formState.isSubmitting
                }
                aria-describedby={
                  onlineNotice ? "online-sign-in-status" : undefined
                }
                onClick={onOnlineLogin}
              >
                {startingOnlineLogin
                  ? t("auth.signingIn")
                  : t("auth.keycloakSignIn")}
              </Button>
              {onlineNotice && (
                <p
                  id="online-sign-in-status"
                  role="status"
                  className="text-sm text-muted-foreground"
                >
                  {onlineNotice}
                </p>
              )}
            </section>
          )}
          {onlineError && (
            <p role="alert" className="text-sm text-destructive">
              {onlineError}
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
