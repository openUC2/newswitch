/**
 * Self-service password change.
 *
 * Changing a password revokes every session for the account, including the one used
 * to ask (see the backend's `UserStore.change_password`), so the response carries a
 * fresh token that replaces the current one - the caller never has to log back in.
 */

import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { BACKEND_API } from "@/constants";
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
import { authFetch } from "@/lib/auth/authFetch";
import { setToken } from "@/lib/auth/token";

export function ChangePasswordDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const reset = () => {
    setCurrentPassword("");
    setNewPassword("");
    setConfirmPassword("");
    setError(null);
  };

  const handleOpenChange = (next: boolean) => {
    if (!next) reset();
    onOpenChange(next);
  };

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);

    if (newPassword !== confirmPassword) {
      setError("The new passwords do not match.");
      return;
    }

    setSubmitting(true);
    try {
      const response = await authFetch(`${BACKEND_API}/auth/me/password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      });

      if (response.status === 401) {
        setError("Current password is incorrect.");
        return;
      }
      if (!response.ok) {
        setError("Could not change the password.");
        return;
      }

      const { token } = (await response.json()) as { token: string };
      setToken(token);
      toast.success("Password changed.");
      handleOpenChange(false);
    } catch {
      setError("Could not reach the microscope backend.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Change password</DialogTitle>
          <DialogDescription>
            You will stay signed in on this device; every other session is
            signed out.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="current-password">Current password</Label>
            <Input
              id="current-password"
              type="password"
              autoComplete="current-password"
              value={currentPassword}
              onChange={(event) => setCurrentPassword(event.target.value)}
              required
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="new-password">New password</Label>
            <Input
              id="new-password"
              type="password"
              autoComplete="new-password"
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              required
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="confirm-password">Confirm new password</Label>
            <Input
              id="confirm-password"
              type="password"
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              required
            />
          </div>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button type="submit" disabled={submitting}>
              {submitting ? "Changing..." : "Change password"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
