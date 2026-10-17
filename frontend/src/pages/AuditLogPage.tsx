/**
 * Admin-only view of the login audit trail (successes, failures, logouts).
 */

import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { BACKEND_API } from "@/constants";
import { AccountMenu } from "@/components/navigation/AccountMenu";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { authFetch } from "@/lib/auth/authFetch";

type LoginEvent = {
  username: string;
  event: "login_success" | "login_failure" | "logout" | "session_expired";
  created_at: string;
};

const EVENT_VARIANT: Record<
  LoginEvent["event"],
  "default" | "destructive" | "secondary"
> = {
  login_success: "default",
  login_failure: "destructive",
  logout: "secondary",
  session_expired: "secondary",
};

export function AuditLogPage() {
  const { t, i18n } = useTranslation();
  const [events, setEvents] = useState<LoginEvent[]>([]);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const response = await authFetch(`${BACKEND_API}/auth/audit`);
      if (!response.ok) throw new Error(`Request failed: ${response.status}`);
      setEvents((await response.json()) as LoginEvent[]);
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t("audit.loadFailed"),
      );
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return (
    <div className="min-h-screen bg-background p-6 text-foreground">
      <AccountMenu />
      <div className="mx-auto flex max-w-3xl flex-col gap-4">
        <Button variant="ghost" size="sm" className="w-fit" asChild>
          <Link to="/">
            <ArrowLeft className="h-4 w-4" />
            {t("navigation.backToMicroscope")}
          </Link>
        </Button>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <div>
              <CardTitle>{t("navigation.auditLog")}</CardTitle>
              <CardDescription>{t("audit.description")}</CardDescription>
            </div>
            <Button
              variant="outline"
              size="icon"
              onClick={reload}
              aria-label={t("common.refresh")}
            >
              <RefreshCw className="h-4 w-4" />
            </Button>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("audit.when")}</TableHead>
                  <TableHead>{t("audit.user")}</TableHead>
                  <TableHead>{t("audit.event")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {events.map((event, index) => (
                  <TableRow key={`${event.created_at}-${index}`}>
                    <TableCell className="text-muted-foreground">
                      {new Intl.DateTimeFormat(i18n.resolvedLanguage, {
                        dateStyle: "medium",
                        timeStyle: "medium",
                      }).format(new Date(event.created_at))}
                    </TableCell>
                    <TableCell className="font-medium">
                      {event.username}
                    </TableCell>
                    <TableCell>
                      <Badge variant={EVENT_VARIANT[event.event]}>
                        {t(`audit.events.${event.event}`)}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))}
                {!loading && events.length === 0 && (
                  <TableRow>
                    <TableCell
                      colSpan={3}
                      className="text-center text-muted-foreground"
                    >
                      {t("audit.noEvents")}
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
