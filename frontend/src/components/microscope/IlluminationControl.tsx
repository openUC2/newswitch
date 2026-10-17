import { Switch } from "@/components/ui/switch";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  useSetIlluminationIntensity,
  useTurnOffIlluminationChannel,
  useTurnOnIllumination,
} from "@/apps/default/hooks/actions";
import { useIlluminationState } from "@/apps/default/hooks/states";
import { cn } from "@/lib/utils";
import { Power, Waves } from "lucide-react";
import { OptimisticSlider } from "../ui/optimistic_slider";
import { ResponsiveGrid } from "../ui/responsive-grid";
import { useTranslation } from "react-i18next";

// Color mapping for wavelengths
const getWavelengthColor = (wavelength: number): string => {
  if (wavelength < 420) return "bg-violet-500";
  if (wavelength < 500) return "bg-blue-500";
  if (wavelength < 570) return "bg-green-500";
  if (wavelength < 600) return "bg-yellow-500";
  if (wavelength < 650) return "bg-orange-500";
  return "bg-red-500";
};

const getWavelengthTextColor = (wavelength: number): string => {
  if (wavelength < 420) return "text-violet-400";
  if (wavelength < 500) return "text-blue-400";
  if (wavelength < 570) return "text-green-400";
  if (wavelength < 600) return "text-yellow-400";
  if (wavelength < 650) return "text-orange-400";
  return "text-red-400";
};

const getKindLabel = (kind: string): string => {
  switch (kind) {
    case "LED":
      return "LED";
    case "LASER":
      return "Laser";
    case "HALOGEN":
      return "Halogen";
    case "ARC":
      return "Arc Lamp";
    default:
      return kind;
  }
};

export function IlluminationControl() {
  const { t } = useTranslation();
  const { data: illuminationState, loading: stateLoading } =
    useIlluminationState({ subscribe: true });
  const { assign: turnOnIllumination, isLoading: isTurningOn } =
    useTurnOnIllumination();
  const { assign: turnOffChannel, isLoading: isTurningOff } =
    useTurnOffIlluminationChannel();
  const { call: setIntensity, isLoading: isSettingIntensity } =
    useSetIlluminationIntensity();

  // Get illuminations from state
  const illuminations = illuminationState?.illuminations ?? [];
  const activeIlluminations = illuminations.filter((i) => i.is_active);
  const activeSlots = new Set(activeIlluminations.map((i) => i.slot));

  const handleToggleSource = (
    channel: number,
    defaultIntensity: number,
    enabled: boolean,
  ) => {
    if (enabled) {
      turnOnIllumination({ channel, intensity: defaultIntensity });
    } else {
      turnOffChannel({ channel });
    }
  };

  const isLoading = isTurningOn || isTurningOff || isSettingIntensity;
  const hasActiveSources = activeSlots.size > 0;

  return (
    <div className="space-y-4">
      {/* Light Sources */}
      <ResponsiveGrid>
        {illuminations?.map((source) => {
          const isActive = source.is_active;
          const currentIntensity = source.intensity;

          return (
            <div
              key={source.slot}
              className={cn(
                "@container min-w-0 overflow-hidden rounded-lg border p-3 transition-all",
                isActive
                  ? "bg-primary/5 border-primary/30"
                  : "bg-muted/30 border-transparent",
              )}
            >
              {/* Source Header */}
              <div className="mb-2 flex flex-col gap-2 @[280px]:flex-row @[280px]:items-start @[280px]:justify-between">
                <div className="flex min-w-0 items-center gap-2">
                  <TooltipProvider>
                    <Tooltip>
                      <TooltipTrigger>
                        <div
                          className={cn(
                            "w-3 h-3 rounded-full",
                            getWavelengthColor(source.wavelength),
                            isActive && "animate-pulse",
                          )}
                        />
                      </TooltipTrigger>
                      <TooltipContent>
                        <p>{source.wavelength}nm</p>
                      </TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                  <span className="truncate text-sm font-medium">
                    {getKindLabel(source.kind)}
                  </span>
                  <span
                    className={cn(
                      "hidden text-xs font-mono @[320px]:inline",
                      getWavelengthTextColor(source.wavelength),
                    )}
                  >
                    {source.wavelength}nm
                  </span>
                </div>
                <div className="flex items-center justify-between gap-2 @[280px]:justify-end">
                  <span className="w-8 text-right font-mono text-xs text-muted-foreground">
                    {isActive ? currentIntensity : 0}%
                  </span>
                  <Switch
                    checked={isActive}
                    onCheckedChange={(checked) =>
                      handleToggleSource(
                        source.slot,
                        source.intensity || 50,
                        checked,
                      )
                    }
                    disabled={isLoading}
                  />
                </div>
              </div>

              {/* Intensity Slider */}
              <div className="flex items-center gap-3 overflow-hidden">
                <Waves className="h-3 w-3 text-muted-foreground" />
                <OptimisticSlider
                  value={[currentIntensity]}
                  onSave={(v) =>
                    setIntensity({ channel: source.slot, intensity: v[0] })
                  }
                  min={source.min_intensity}
                  max={source.max_intensity}
                  step={1}
                  className="flex-1"
                  disabled={isLoading || !isActive}
                />
              </div>

              {/* Channel indicator */}
              <div className="mt-2 grid grid-cols-2 gap-x-2 gap-y-1 text-xs text-muted-foreground @[240px]:flex @[240px]:items-center">
                <span className="text-xs text-muted-foreground">
                  Ch {source.channel}
                </span>
                <span className="hidden text-xs text-muted-foreground @[240px]:inline">
                  •
                </span>
                <span className="hidden text-xs text-muted-foreground @[300px]:inline">
                  {t("common.slot", { slot: source.slot })}
                </span>
              </div>
            </div>
          );
        })}

        {(!illuminations || illuminations.length === 0) && !stateLoading && (
          <div className="text-center py-4 text-sm text-muted-foreground col-span-full">
            {t("microscope.noLightSources")}
          </div>
        )}
      </ResponsiveGrid>

      {/* Quick Off All Button */}
      {hasActiveSources && (
        <button
          onClick={() => {
            // Turn off all active channels
            activeIlluminations?.forEach((source) => {
              turnOffChannel({ channel: source.channel });
            });
          }}
          disabled={isLoading}
          className="w-full flex items-center justify-center gap-2 py-2 px-3 rounded-lg bg-destructive/10 hover:bg-destructive/20 text-destructive text-sm font-medium transition-colors disabled:opacity-50"
        >
          <Power className="h-4 w-4" />
          {t("microscope.turnOffAll")}
        </button>
      )}
    </div>
  );
}
