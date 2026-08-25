/**
 * The floating account control: change password, admin shortcuts, log out.
 *
 * Deliberately independent of the microscope's rekuest scope (unlike
 * `AppNavigationChrome`, which it lives inside) so the same menu also works standalone
 * on the admin pages, which do not connect to the microscope backend at all.
 */

import { useState } from "react";
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

export function AccountMenu({ className }: { className?: string }) {
  const { username, role, logout } = useAuth();
  const navigate = useNavigate();
  const [passwordDialogOpen, setPasswordDialogOpen] = useState(false);

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="Account menu"
            className={cn(
              "fixed right-3 top-3 z-50 h-8 w-8 bg-background/70 backdrop-blur hover:bg-background",
              className,
            )}
          >
            <ShieldUser className="h-4 w-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {username && (
            <div className="px-2 py-1.5 text-xs text-muted-foreground">
              {username} · {role}
            </div>
          )}
          {role === "admin" && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={() => navigate("/admin/users")}>
                <ShieldUser className="h-4 w-4" />
                Manage users
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => navigate("/admin/audit")}>
                <ScrollText className="h-4 w-4" />
                Audit log
              </DropdownMenuItem>
            </>
          )}
          <DropdownMenuSeparator />
          <DropdownMenuItem onClick={() => setPasswordDialogOpen(true)}>
            <KeyRound className="h-4 w-4" />
            Change password
          </DropdownMenuItem>
          <DropdownMenuItem variant="destructive" onClick={logout}>
            <LogOut className="h-4 w-4" />
            Log out
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <ChangePasswordDialog
        open={passwordDialogOpen}
        onOpenChange={setPasswordDialogOpen}
      />
    </>
  );
}
