import { useState } from "react";
import { LayoutDashboard } from "lucide-react";
import { bloks, type BlokKey } from "@/apps/default/bloks";
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

const BLOK_KEYS = Object.keys(bloks) as BlokKey[];

/** Lists the bloks the backend declares; opening one draws it, live, in a dialog. */
export function BloksPanel() {
  const [open, setOpen] = useState<BlokKey | null>(null);

  if (BLOK_KEYS.length === 0) return null;

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
        {BLOK_KEYS.map((key) => (
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
              {(open && bloks[open].description) || "Blok"}
            </DialogDescription>
          </DialogHeader>
          {open && (
            <div className="max-h-[70vh] overflow-auto">
              <NewswitchBlok blokKey={open} chrome="none" sizing="intrinsic" />
            </div>
          )}
        </DialogContent>
      </Dialog>
    </Card>
  );
}
