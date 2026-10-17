import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  useSwitchObjective,
  useToggleObjective,
} from "@/apps/default/hooks/actions";
import { useObjectiveState } from "@/apps/default/hooks/states";
import { cn } from "@/lib/utils";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

export function ObjectiveControl() {
  const { t } = useTranslation();
  const { data: objectiveState, loading: stateLoading } = useObjectiveState({
    subscribe: true,
  });
  const { assign: switchObjective, isLoading: isSwitching } =
    useSwitchObjective();
  // NOTE: only the loading flag is used - no control in this panel calls the toggle
  // action. Kept so isLoading still reflects an in-flight toggle from elsewhere.
  const { isLoading: isToggling } = useToggleObjective();

  const [selectedSlot, setSelectedSlot] = useState<number | null>(null);
  const [syncedSlot, setSyncedSlot] = useState<number | null>(null);

  // Re-sync the local selection whenever the server's slot changes. This is React's
  // "adjust state during render" pattern rather than a setState-in-effect, which triggers
  // a second render pass (and trips react-hooks/set-state-in-effect). Same semantics:
  // a change from the server wins over the local selection.
  const serverSlot = objectiveState?.slot ?? null;
  if (serverSlot !== null && serverSlot !== syncedSlot) {
    setSyncedSlot(serverSlot);
    setSelectedSlot(serverSlot);
  }

  const handleSelectObjective = (slot: number) => {
    setSelectedSlot(slot);
    switchObjective({ slot });
  };

  const handlePrevious = () => {
    if (!objectiveState?.mounted_lenses?.length) return;
    const currentIndex = objectiveState.mounted_lenses.findIndex(
      (l) => l.slot === objectiveState.slot,
    );
    const prevIndex =
      currentIndex <= 0
        ? objectiveState.mounted_lenses.length - 1
        : currentIndex - 1;
    switchObjective({ slot: objectiveState.mounted_lenses[prevIndex].slot });
  };

  const handleNext = () => {
    if (!objectiveState?.mounted_lenses?.length) return;
    const currentIndex = objectiveState.mounted_lenses.findIndex(
      (l) => l.slot === objectiveState.slot,
    );
    const nextIndex =
      currentIndex >= objectiveState.mounted_lenses.length - 1
        ? 0
        : currentIndex + 1;
    switchObjective({ slot: objectiveState.mounted_lenses[nextIndex].slot });
  };

  const currentLens = objectiveState?.mounted_lenses?.find(
    (l) => l.slot === objectiveState?.slot,
  );

  const isLoading = isSwitching || isToggling;

  return (
    <div className="space-y-4">
      {/* Current Objective Display */}
      {currentLens && (
        <div className="@container flex items-center gap-2">
          <button
            onClick={handlePrevious}
            disabled={
              isLoading || (objectiveState?.mounted_lenses?.length ?? 0) <= 1
            }
            className="p-2 rounded-lg bg-muted/50 hover:bg-muted transition-colors disabled:opacity-50"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>

          <div className="min-w-0 flex-1 rounded-lg border border-primary/20 bg-gradient-to-r from-primary/10 to-primary/5 p-4">
            <div className="flex flex-col gap-3 @[320px]:flex-row @[320px]:items-center">
              <div className="h-14 w-14 rounded-full bg-primary/20 flex items-center justify-center shrink-0">
                <span className="text-xl font-bold text-primary">
                  {currentLens.magnification}×
                </span>
              </div>
              <div className="min-w-0 flex-1">
                <h3 className="text-base font-semibold truncate">
                  {currentLens.name}
                </h3>
                <div className="mt-1 grid grid-cols-1 gap-x-3 gap-y-1 text-xs text-muted-foreground @[360px]:grid-cols-3">
                  <span>NA {currentLens.numerical_aperture.toFixed(2)}</span>
                  <span>WD {currentLens.working_distance}mm</span>
                  <span className="hidden @[360px]:inline">
                    Bin {currentLens.binning_factor}×
                  </span>
                </div>
              </div>
            </div>
          </div>

          <button
            onClick={handleNext}
            disabled={
              isLoading || (objectiveState?.mounted_lenses?.length ?? 0) <= 1
            }
            className="p-2 rounded-lg bg-muted/50 hover:bg-muted transition-colors disabled:opacity-50"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* Objective Carousel/Grid */}
      <div className="space-y-2">
        <span className="text-xs text-muted-foreground">
          {t("microscope.availableLenses")}
        </span>
        <div className="flex gap-2 overflow-x-auto pb-2">
          {objectiveState?.mounted_lenses?.map((lens) => {
            const isActive = objectiveState?.slot === lens.slot;
            const isSelected = selectedSlot === lens.slot;

            return (
              <TooltipProvider key={lens.slot}>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button
                      onClick={() => handleSelectObjective(lens.slot)}
                      disabled={isLoading}
                      className={cn(
                        "relative flex min-w-[4rem] max-w-[5.5rem] flex-col items-center justify-center overflow-hidden rounded-lg border p-3 text-center transition-all",
                        isActive
                          ? "bg-primary text-primary-foreground border-primary"
                          : isSelected
                            ? "bg-secondary border-secondary"
                            : "bg-muted/30 border-transparent hover:bg-muted/50",
                        isLoading && "opacity-50 cursor-not-allowed",
                      )}
                    >
                      {isActive && (
                        <span className="absolute top-1 right-1 w-2 h-2 bg-green-400 rounded-full animate-pulse" />
                      )}
                      <span className="text-lg font-bold">
                        {lens.magnification}×
                      </span>
                      <span className="text-xs opacity-80 truncate max-w-full">
                        {lens.name.split(" ")[0]}
                      </span>
                    </button>
                  </TooltipTrigger>
                  <TooltipContent side="bottom">
                    <div className="text-xs space-y-1">
                      <p className="font-medium">{lens.name}</p>
                      <p>NA: {lens.numerical_aperture}</p>
                      <p>
                        {t("microscope.workingDistance")}:{" "}
                        {lens.working_distance} mm
                      </p>
                      <p>
                        {t("microscope.binning")}: {lens.binning_factor}×
                      </p>
                      <p>{t("common.slot", { slot: lens.slot })}</p>
                    </div>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            );
          })}

          {(!objectiveState?.mounted_lenses ||
            objectiveState.mounted_lenses.length === 0) &&
            !stateLoading && (
              <div className="text-center py-4 text-sm text-muted-foreground w-full">
                {t("microscope.noObjectives")}
              </div>
            )}
        </div>
      </div>
    </div>
  );
}
