import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import {
  useActivateDetector,
  useDeactivateDetector,
  useUpdateDetector,
} from "@/apps/default/hooks/actions";
import { useCameraState } from "@/apps/default/hooks/states";
import { cn } from "@/lib/utils";
import { Gauge, MonitorUp, Timer } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { OptimisticSlider } from "../ui/optimistic_slider";
import { ResponsiveGrid } from "../ui/responsive-grid";

export function CameraControl() {
  const { t, i18n } = useTranslation();
  const formatNumber = (value: number, digits = 1) =>
    new Intl.NumberFormat(i18n.resolvedLanguage, {
      maximumFractionDigits: digits,
      minimumFractionDigits: digits,
    }).format(value);
  const { data: cameraState, loading: stateLoading } = useCameraState({
    subscribe: true,
  });
  const { assign: activateDetector, isLoading: isActivating } =
    useActivateDetector();
  const { assign: deactivateDetector, isLoading: isDeactivating } =
    useDeactivateDetector();
  const { call: updateDetector, isLoading: isUpdating } = useUpdateDetector();

  // Local state for slider dragging. Exposure no longer needs it: that slider commits
  // through OptimisticSlider's onSave. Gain still uses the change/commit pair below.
  const [localGains, setLocalGains] = useState<Record<number, number>>({});
  const [selectedDetectorSlot, setSelectedDetectorSlot] = useState<
    number | null
  >(null);

  const detectors = cameraState?.detectors ?? [];

  const handleToggleDetector = (slot: number, enabled: boolean) => {
    if (enabled) {
      activateDetector({ slot });
    } else {
      deactivateDetector({ slot });
    }
  };

  const handleGainChange = (slot: number, value: number) => {
    setLocalGains((prev) => ({ ...prev, [slot]: value }));
  };

  const handleGainCommit = (slot: number) => {
    const gain = localGains[slot];
    if (gain !== undefined) {
      updateDetector({ slot, gain });
      setLocalGains((prev) => {
        const next = { ...prev };
        delete next[slot];
        return next;
      });
    }
  };

  // Live-view and capture controls live in SettingsPanel; this panel only owns the
  // per-detector settings.
  const isDetectorLoading = isActivating || isDeactivating;

  return (
    <div className="space-y-4">
      {/* Detectors */}
      <ResponsiveGrid>
        {detectors?.map((detector) => {
          const isActive = detector.is_active;
          const currentExposure =
            detector.current_exposure_time ?? detector.min_exposure_time;
          const currentGain =
            localGains[detector.slot] ??
            detector.current_gain ??
            detector.min_gain;
          const isExpanded = selectedDetectorSlot === detector.slot;

          return (
            <div
              key={detector.slot}
              className={cn(
                "@container min-w-0 overflow-hidden rounded-lg border transition-all",
                isActive
                  ? "bg-primary/5 border-primary/30"
                  : "bg-muted/30 border-transparent",
              )}
            >
              {/* Detector Header */}
              <div
                className="cursor-pointer p-3"
                onClick={() =>
                  setSelectedDetectorSlot(isExpanded ? null : detector.slot)
                }
              >
                <div className="flex flex-col gap-2 @[280px]:flex-row @[280px]:items-start @[280px]:justify-between">
                  <div className="flex min-w-0 items-center gap-2">
                    <MonitorUp
                      className={cn(
                        "h-4 w-4 shrink-0",
                        isActive && "text-green-500",
                      )}
                    />
                    <span className="truncate text-sm font-medium">
                      {detector.name}
                    </span>
                  </div>
                  <div className="flex items-center justify-between gap-2 @[280px]:justify-end">
                    {isActive && (
                      <span className="hidden text-xs font-mono text-muted-foreground @[340px]:inline">
                        {formatNumber(detector.current_exposure_time, 0)} ms /{" "}
                        {formatNumber(detector.current_gain)}×
                      </span>
                    )}
                    <Switch
                      checked={isActive}
                      onCheckedChange={(checked) =>
                        handleToggleDetector(detector.slot, checked)
                      }
                      disabled={isDetectorLoading}
                      onClick={(e) => e.stopPropagation()}
                    />
                  </div>
                </div>

                {/* Compact info */}
                <div className="mt-1 grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-muted-foreground @[360px]:grid-cols-3">
                  <span className="text-xs text-muted-foreground">
                    {detector.width}×{detector.height}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {detector.pixel_size_um}µm
                  </span>
                  <span className="hidden text-xs text-muted-foreground @[360px]:inline">
                    {t("common.slot", { slot: detector.slot })}
                  </span>
                </div>
              </div>

              {/* Expanded Controls */}
              {isExpanded && isActive && (
                <div className="px-3 pb-3 space-y-3 border-t border-border/50 pt-3">
                  {/* Exposure Control */}
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <Timer className="h-3 w-3 text-muted-foreground" />
                        <span className="text-xs text-muted-foreground">
                          {t("microscope.exposure")}
                        </span>
                      </div>
                      <span className="text-xs font-mono">
                        {formatNumber(currentExposure)} ms
                      </span>
                    </div>
                    <OptimisticSlider
                      value={[currentExposure]}
                      onSave={(v) =>
                        updateDetector({
                          slot: detector.slot,
                          exposure_time: v[0],
                        })
                      }
                      min={detector.min_exposure_time}
                      max={detector.max_exposure_time}
                      step={0.1}
                      className="flex-1"
                      disabled={isUpdating}
                    />
                    {detector.preset_exposure_times?.length > 0 && (
                      <div className="hidden flex-wrap gap-1 @[360px]:flex">
                        {detector.preset_exposure_times
                          .slice(0, 6)
                          .map((val) => (
                            <Button
                              key={val}
                              size="sm"
                              variant={
                                Math.abs(
                                  (detector.current_exposure_time ?? 0) - val,
                                ) < 0.5
                                  ? "default"
                                  : "outline"
                              }
                              onClick={() =>
                                updateDetector({
                                  slot: detector.slot,
                                  exposure_time: val,
                                })
                              }
                              className="h-6 text-xs px-2"
                              disabled={isUpdating}
                            >
                              {val >= 1000 ? `${val / 1000}s` : `${val}ms`}
                            </Button>
                          ))}
                      </div>
                    )}
                  </div>

                  {/* Gain Control */}
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <Gauge className="h-3 w-3 text-muted-foreground" />
                        <span className="text-xs text-muted-foreground">
                          {t("microscope.gain")}
                        </span>
                      </div>
                      <span className="text-xs font-mono">
                        {formatNumber(currentGain)}×
                      </span>
                    </div>
                    <OptimisticSlider
                      value={[currentGain]}
                      onValueChange={(v) =>
                        handleGainChange(detector.slot, v[0])
                      }
                      onValueCommit={() => handleGainCommit(detector.slot)}
                      min={detector.min_gain}
                      max={detector.max_gain}
                      step={0.1}
                      className="flex-1"
                      disabled={isUpdating}
                    />
                    <div className="hidden gap-1 @[360px]:flex">
                      {[1, 2, 4, 8, 16, 32]
                        .filter(
                          (v) =>
                            v >= detector.min_gain && v <= detector.max_gain,
                        )
                        .map((val) => (
                          <Button
                            key={val}
                            size="sm"
                            variant={
                              Math.abs((detector.current_gain ?? 0) - val) < 0.1
                                ? "default"
                                : "outline"
                            }
                            onClick={() =>
                              updateDetector({ slot: detector.slot, gain: val })
                            }
                            className="flex-1 h-6 text-xs px-1"
                            disabled={isUpdating}
                          >
                            {val}×
                          </Button>
                        ))}
                    </div>
                  </div>
                </div>
              )}
            </div>
          );
        })}

        {(!detectors || detectors.length === 0) && !stateLoading && (
          <div className="text-center py-4 text-sm text-muted-foreground col-span-full">
            No detectors available
          </div>
        )}
      </ResponsiveGrid>
    </div>
  );
}
