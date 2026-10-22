/**
 * The floating account control: change password, admin shortcuts, log out.
 *
 * Deliberately independent of the microscope's arkitekt scope (unlike
 * `AppNavigationChrome`, which it lives inside) so the same menu also works standalone
 * on the admin pages, which do not connect to the microscope backend at all.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { LogOut, ScrollText, ShieldUser, KeyRound } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAuth } from "@/lib/auth/context";
import { cn } from "@/lib/utils";
import { ChangePasswordDialog } from "./ChangePasswordDialog";
import { LanguageMenu } from "./LanguageMenu";

/**
 * The account menu and the language menu. `corner` (the default) floats them in the
 * top-right corner; `inline` places them in a bar (the microscope's bottom bar).
 */
export function AccountMenu({
  className,
  placement = "corner",
}: {
  className?: string;
  placement?: "corner" | "inline";
}) {
  const inline = placement === "inline";
  const { username, role, logout } = useAuth();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const [passwordDialogOpen, setPasswordDialogOpen] = useState(false);

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={t("auth.accountMenu")}
            className={cn(
              inline
                ? "h-8 w-8"
                : "fixed right-3 top-3 z-50 h-8 w-8 bg-background/70 backdrop-blur hover:bg-background",
              className,
            )}
          >
            <ShieldUser className="h-4 w-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" side={inline ? "top" : "bottom"}>
          {username && (
            <div className="px-2 py-1.5 text-xs text-muted-foreground">
              {username} · {role ? t(`roles.${role}`) : ""}
            </div>
          )}
          {role === "admin" && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={() => navigate("/admin/users")}>
                <ShieldUser className="h-4 w-4" />
                {t("navigation.manageUsers")}
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => navigate("/admin/audit")}>
                <ScrollText className="h-4 w-4" />
                {t("navigation.auditLog")}
              </DropdownMenuItem>
            </>
          )}
          <DropdownMenuSeparator />
          <DropdownMenuItem onClick={() => setPasswordDialogOpen(true)}>
            <KeyRound className="h-4 w-4" />
            {t("auth.changePassword")}
          </DropdownMenuItem>
          <DropdownMenuItem variant="destructive" onClick={logout}>
            <LogOut className="h-4 w-4" />
            {t("auth.logOut")}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <LanguageMenu
        className={
          inline
            ? "order-first"
            : "fixed right-12 top-3 z-50 hover:bg-background"
        }
      />
      <ChangePasswordDialog
        open={passwordDialogOpen}
        onOpenChange={setPasswordDialogOpen}
      />
    </>
  );
}
