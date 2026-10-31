import { useTune } from "@/apps/default/hooks/actions";
import { useSourceState } from "@/apps/default/hooks/states/SourceState";
import { OptimisticSlider } from "@/components/ui/optimistic_slider";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import { Power, Waves } from "lucide-react";
import { useTranslation } from "react-i18next";
import { getWavelengthColor } from "./wavelength";

/** Where light starts: each on or off, at a power in its own unit. */
export function SourceControl() {
  const { t } = useTranslation();
  const { data, loading } = useSourceState({ subscribe: true });
  const { call: tune, isLoading } = useTune();
  const sources = Object.values(data?.sources ?? {});
  const lit = sources.filter((source) => source.on && source.power_variable);

  return (
    <div className="space-y-4">
      {sources.map((source) => (
        <div
          key={source.name}
          className={cn(
            "rounded-lg border p-3 transition-colors",
            source.on
              ? "border-primary/30 bg-primary/5"
              : "border-transparent bg-muted/30",
          )}
        >
          <div className="mb-2 flex items-center justify-between gap-2">
            <div className="flex min-w-0 items-center gap-2">
              <div
                className={cn(
                  "h-3 w-3 rounded-full",
                  getWavelengthColor(source.wavelength),
                  source.on && "animate-pulse",
                )}
              />
              <span className="truncate text-sm font-medium">
                {source.name}
              </span>
              <span className="font-mono text-xs text-muted-foreground">
                {source.lines.map((line) => `${line} nm`).join(", ")}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs text-muted-foreground">
                {Number(source.power.toFixed(3))} mW
              </span>
              {source.power_variable && (
                <Switch
                  checked={source.on}
                  disabled={isLoading}
                  onCheckedChange={(on) =>
                    tune({
                      name: source.power_variable as string,
                      to: on ? source.lit_power : 0,
                    })
                  }
                />
              )}
            </div>
          </div>
          {source.power_variable && (
            <div className="flex items-center gap-3 overflow-hidden">
              <Waves className="h-3 w-3 text-muted-foreground" />
              <OptimisticSlider
                value={[source.power]}
                onSave={(v) =>
                  tune({ name: source.power_variable as string, to: v[0] })
                }
                min={0}
                max={source.max_power}
                className="flex-1"
                disabled={isLoading || !source.on}
              />
            </div>
          )}
        </div>
      ))}

      {sources.length === 0 && !loading && (
        <div className="py-4 text-center text-sm text-muted-foreground">
          {t("microscope.noLightSources")}
        </div>
      )}

      {lit.length > 0 && (
        <button
          onClick={() =>
            lit.forEach((source) =>
              tune({ name: source.power_variable as string, to: 0 }),
            )
          }
          disabled={isLoading}
          className="flex w-full items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm text-muted-foreground hover:bg-muted"
        >
          <Power className="h-4 w-4" />
          {t("microscope.turnOffAll")}
        </button>
      )}
    </div>
  );
}
