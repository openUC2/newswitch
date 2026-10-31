import { useTune } from "@/apps/default/hooks/actions";
import { useOpticsState } from "@/apps/default/hooks/states/OpticsState";
import { useSourceState } from "@/apps/default/hooks/states/SourceState";
import { OptimisticSlider } from "@/components/ui/optimistic_slider";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import type { CSSProperties } from "react";
import { useTranslation } from "react-i18next";

/** The theme's colour of a spectrum, as what a card's classes read as `--c`. */
const colored = (name: string, color?: string | null) =>
  ({
    [name]: color ? `var(--spectrum-${color})` : "var(--muted-foreground)",
  }) as CSSProperties;

/** Where light starts, each as a card of its own colour: on or off, at a power in mW, and what it
 * makes arrive. The colour is the server's, from one function; it names no dye, as it knows none. */
export function SourceControl() {
  const { t } = useTranslation();
  const { data, loading } = useSourceState({ subscribe: true });
  const { data: optics } = useOpticsState({ subscribe: true });
  const { call: tune, isLoading } = useTune();
  const sources = Object.values(data?.sources ?? {});

  return (
    <div className="flex flex-col gap-3">
      {sources.map((source) => {
        const band = optics?.sources[source.name];
        const variable = source.power_variable;
        return (
          <div
            key={source.name}
            style={{
              ...colored("--c", source.color),
              ...colored("--b", band?.band_color),
            }}
            className="relative overflow-hidden rounded-2xl border border-border/60 bg-card/70 p-4 shadow-xl"
          >
            <div
              className={cn(
                "pointer-events-none absolute -right-12 -top-12 size-44 rounded-full blur-3xl",
                source.on ? "bg-[var(--c)] opacity-25" : "bg-muted opacity-10",
              )}
            />
            <div className="relative flex items-start justify-between gap-3">
              <div className="flex min-w-0 flex-col gap-1">
                <span className="truncate text-[10px] font-medium uppercase tracking-[0.2em] text-[var(--c)]">
                  {source.name}
                </span>
                <div className="flex items-baseline gap-1.5">
                  <span className="text-4xl font-semibold tabular-nums tracking-tight">
                    {source.lines.join(" · ")}
                  </span>
                  <span className="text-sm text-muted-foreground">nm</span>
                </div>
                <span className="text-xs capitalize text-muted-foreground">
                  {source.emits}
                </span>
              </div>
              {variable && (
                <Switch
                  checked={source.on}
                  disabled={isLoading}
                  className="past:hidden data-[state=checked]:bg-[var(--c)]"
                  onCheckedChange={(on) =>
                    tune({ name: variable, to: on ? source.lit_power : 0 })
                  }
                />
              )}
            </div>
            <div className="relative mt-4 flex items-center gap-1.5">
              <span
                className={cn(
                  "size-2.5 rounded-full",
                  source.on ? "bg-[var(--c)]" : "bg-muted-foreground/40",
                )}
              />
              <div
                className={cn(
                  "h-0.5 flex-1 rounded-full",
                  source.on
                    ? "bg-[var(--c)] opacity-60"
                    : "bg-muted-foreground/20",
                )}
              />
              <span className="rounded-md border border-border px-1.5 py-0.5 text-[10px] text-muted-foreground">
                {t("microscope.sample")}
              </span>
              <div
                className={cn(
                  "h-0.5 flex-1 rounded-full",
                  source.on && band?.band_nm
                    ? "bg-[var(--b)] opacity-60"
                    : "bg-muted-foreground/20",
                )}
              />
              {band?.band_nm != null && (
                <span
                  className={cn(
                    "text-[10px] tabular-nums",
                    source.on ? "text-[var(--b)]" : "text-muted-foreground",
                  )}
                >
                  ~{Math.round(band.band_nm)} nm
                </span>
              )}
            </div>
            {source.on || !variable ? (
              <div className="relative mt-5">
                <div className="flex items-end justify-between">
                  <span className="text-[10px] font-medium uppercase tracking-[0.2em] text-muted-foreground">
                    {t("microscope.power")}
                  </span>
                  <span className="text-2xl font-semibold tabular-nums text-[var(--c)]">
                    {Number(source.power.toPrecision(3))} mW
                  </span>
                </div>
                {variable && (
                  <OptimisticSlider
                    className="mt-2 past:hidden [&_[data-slot=slider-range]]:bg-[var(--c)] [&_[data-slot=slider-thumb]]:border-[var(--c)]"
                    value={[source.power]}
                    min={0}
                    max={source.max_power}
                    step={source.max_power / 100}
                    disabled={isLoading}
                    onSave={(v) => tune({ name: variable, to: v[0] })}
                  />
                )}
              </div>
            ) : (
              <span className="relative mt-4 block text-xs text-muted-foreground">
                {t("microscope.sourceOff")}
              </span>
            )}
          </div>
        );
      })}
      {sources.length === 0 && !loading && (
        <div className="py-4 text-center text-sm text-muted-foreground">
          {t("microscope.noLightSources")}
        </div>
      )}
    </div>
  );
}
