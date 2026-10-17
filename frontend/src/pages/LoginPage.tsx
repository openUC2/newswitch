import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { z } from "zod";
import { useTranslation } from "react-i18next";
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

type LoginValues = { username: string; password: string };

export function LoginPage() {
  const { isAuthenticated, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useTranslation();
  const [error, setError] = useState<string | null>(null);

  const loginSchema = z.object({
    username: z.string().min(1, t("auth.enterUsername")),
    password: z.string().min(1, t("auth.enterPassword")),
  });

  const form = useForm<LoginValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { username: "", password: "" },
  });

  // Where the guard bounced the user from, so a deep link survives logging in.
  const from =
    (location.state as { from?: Location } | null)?.from?.pathname ?? "/";

  if (isAuthenticated) {
    return <Navigate to={from} replace />;
  }

  const onSubmit = async (values: LoginValues) => {
    setError(null);
    try {
      await login(values.username, values.password);
      navigate(from, { replace: true });
    } catch (caught) {
      setError(
        caught instanceof InvalidCredentialsError
          ? t("auth.invalidCredentials")
          : t("auth.backendUnavailable"),
      );
    }
  };

  return (
    <div className="dark flex min-h-screen items-center justify-center bg-background p-4 text-foreground">
      <LanguageMenu className="fixed right-3 top-3" />
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>{t("common.appName")}</CardTitle>
          <CardDescription>{t("auth.signInDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          <Form {...form}>
            <form
              onSubmit={form.handleSubmit(onSubmit)}
              className="flex flex-col gap-4"
            >
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

              {error && (
                <p role="alert" className="text-sm text-destructive">
                  {error}
                </p>
              )}

              <Button type="submit" disabled={form.formState.isSubmitting}>
                {form.formState.isSubmitting
                  ? t("auth.signingIn")
                  : t("auth.signIn")}
              </Button>
            </form>
          </Form>
        </CardContent>
      </Card>
    </div>
  );
}
