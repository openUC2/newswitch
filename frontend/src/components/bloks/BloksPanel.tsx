import { useState } from "react";
import { LayoutDashboard } from "lucide-react";
import { useBackendUi } from "@/lib/blok/backendUi";
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
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { NewswitchBlok } from "./NewswitchBlok";

/** Lists the bloks the backend declares; opening one draws it, live, in a dialog. */
export function BloksPanel() {
  const [open, setOpen] = useState<string | null>(null);
  const ui = useBackendUi();
  const bloks = ui.status === "ready" ? ui.bloks : {};
  const keys = Object.keys(bloks);
  const opened = open ? bloks[open] : undefined;

  if (keys.length === 0) return null;

  return (
    <Card className="gap-3 py-4">
      <CardHeader className="px-4">
        <CardTitle className="flex items-center gap-2 text-sm">
          <LayoutDashboard className="size-4" />
          Bloks
        </CardTitle>
        <CardDescription className="text-xs">
          Panels declared by the backend.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-wrap gap-2 px-4">
        {keys.map((key) => (
          <Button
            key={key}
            size="sm"
            variant="outline"
            onClick={() => setOpen(key)}
          >
            {key}
          </Button>
        ))}
      </CardContent>

      <Dialog
        open={open !== null}
        onOpenChange={(next) => !next && setOpen(null)}
      >
        <DialogContent className="w-auto max-w-[calc(100vw-2rem)] sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>{open}</DialogTitle>
            <DialogDescription>
              {opened?.description || "Blok"}
            </DialogDescription>
          </DialogHeader>
          {opened && (
            <div className="max-h-[70vh] overflow-auto">
              <NewswitchBlok blok={opened} chrome="none" sizing="intrinsic" />
            </div>
          )}
        </DialogContent>
      </Dialog>
    </Card>
  );
}
