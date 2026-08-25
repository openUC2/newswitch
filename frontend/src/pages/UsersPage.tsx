/**
 * Admin-only account management: create, change role, enable/disable, reset
 * password, delete. Talks straight to the `/auth/users` API - no rekuest scope
 * involved, so this page (and the guard in front of it) works even if the
 * microscope backend connection is otherwise unhealthy.
 */

import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { BACKEND_API } from "@/constants";
import { AccountMenu } from "@/components/navigation/AccountMenu";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
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
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { authFetch } from "@/lib/auth/authFetch";
import { useAuth, type Role } from "@/lib/auth/context";

const ROLES: Role[] = ["admin", "operator", "viewer", "analyst"];

type ApiUser = {
  username: string;
  role: Role;
  disabled: boolean;
};

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await authFetch(`${BACKEND_API}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as {
      detail?: string;
    } | null;
    throw new Error(body?.detail ?? `Request failed: ${response.status}`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function UsersPage() {
  const { username: myUsername } = useAuth();
  const [users, setUsers] = useState<ApiUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [createOpen, setCreateOpen] = useState(false);
  const [passwordTarget, setPasswordTarget] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      setUsers(await fetchJson<ApiUser[]>("/auth/users"));
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Could not load users.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const updateUser = async (
    user: ApiUser,
    patch: Partial<Pick<ApiUser, "role" | "disabled">>,
  ) => {
    try {
      await fetchJson(`/auth/users/${encodeURIComponent(user.username)}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      });
      await reload();
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Could not update user.",
      );
    }
  };

  const deleteUser = async (username: string) => {
    try {
      await fetchJson(`/auth/users/${encodeURIComponent(username)}`, {
        method: "DELETE",
      });
      toast.success(`Deleted '${username}'.`);
      await reload();
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Could not delete user.",
      );
    } finally {
      setDeleteTarget(null);
    }
  };

  return (
    <div className="min-h-screen bg-background p-6 text-foreground">
      <AccountMenu />
      <div className="mx-auto flex max-w-3xl flex-col gap-4">
        <Button variant="ghost" size="sm" className="w-fit" asChild>
          <Link to="/">
            <ArrowLeft className="h-4 w-4" />
            Back to microscope
          </Link>
        </Button>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <div>
              <CardTitle>Users</CardTitle>
              <CardDescription>Manage accounts and roles.</CardDescription>
            </div>
            <Button onClick={() => setCreateOpen(true)}>Add user</Button>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Username</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead>Enabled</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {users.map((user) => (
                  <TableRow key={user.username}>
                    <TableCell className="font-medium">
                      {user.username}
                      {user.username === myUsername && (
                        <Badge variant="secondary" className="ml-2">
                          you
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell>
                      <Select
                        value={user.role}
                        onValueChange={(role) =>
                          updateUser(user, { role: role as Role })
                        }
                      >
                        <SelectTrigger size="sm" className="w-32">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {ROLES.map((role) => (
                            <SelectItem key={role} value={role}>
                              {role}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </TableCell>
                    <TableCell>
                      <Switch
                        checked={!user.disabled}
                        onCheckedChange={(checked) =>
                          updateUser(user, { disabled: !checked })
                        }
                      />
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setPasswordTarget(user.username)}
                        >
                          Reset password
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          disabled={user.username === myUsername}
                          onClick={() => setDeleteTarget(user.username)}
                          aria-label={`Delete ${user.username}`}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
                {!loading && users.length === 0 && (
                  <TableRow>
                    <TableCell
                      colSpan={4}
                      className="text-center text-muted-foreground"
                    >
                      No users yet.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>

      <CreateUserDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={reload}
      />
      <SetPasswordDialog
        username={passwordTarget}
        onOpenChange={(open) => !open && setPasswordTarget(null)}
      />

      <AlertDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete '{deleteTarget}'?</AlertDialogTitle>
            <AlertDialogDescription>
              This permanently removes the account and signs it out everywhere.
              This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => deleteTarget && deleteUser(deleteTarget)}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

function CreateUserDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: () => void;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("operator");
  const [submitting, setSubmitting] = useState(false);

  const reset = () => {
    setUsername("");
    setPassword("");
    setRole("operator");
  };

  const onSubmit = async () => {
    setSubmitting(true);
    try {
      await fetchJson("/auth/users", {
        method: "POST",
        body: JSON.stringify({ username, password, role }),
      });
      toast.success(`Created '${username}'.`);
      reset();
      onOpenChange(false);
      onCreated();
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Could not create user.",
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add user</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="new-username">Username</Label>
            <Input
              id="new-username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              autoFocus
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="new-user-password">Password</Label>
            <Input
              id="new-user-password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label>Role</Label>
            <Select
              value={role}
              onValueChange={(value) => setRole(value as Role)}
            >
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {ROLES.map((option) => (
                  <SelectItem key={option} value={option}>
                    {option}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        <DialogFooter>
          <Button
            onClick={onSubmit}
            disabled={submitting || !username || !password}
          >
            {submitting ? "Creating..." : "Create"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function SetPasswordDialog({
  username,
  onOpenChange,
}: {
  username: string | null;
  onOpenChange: (open: boolean) => void;
}) {
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async () => {
    if (!username) return;
    setSubmitting(true);
    try {
      await fetchJson(`/auth/users/${encodeURIComponent(username)}/password`, {
        method: "POST",
        body: JSON.stringify({ password }),
      });
      toast.success(`Password for '${username}' reset.`);
      setPassword("");
      onOpenChange(false);
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Could not reset password.",
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={username !== null} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Reset password for '{username}'</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-2">
          <Label htmlFor="reset-password">New password</Label>
          <Input
            id="reset-password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoFocus
          />
        </div>
        <DialogFooter>
          <Button onClick={onSubmit} disabled={submitting || !password}>
            {submitting ? "Resetting..." : "Reset password"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
