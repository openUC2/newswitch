import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useSwitchFilter, useToggleFilter } from "@/apps/default/hooks/actions";
import { useFilterBankState } from "@/apps/default/hooks/states";
import { cn } from "@/lib/utils";
import { RotateCw } from "lucide-react";
import { ResponsiveGrid } from "../ui/responsive-grid";
import { useTranslation } from "react-i18next";

// Color mapping for filter wavelengths
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

export function FilterBankControl() {
  const { t } = useTranslation();
  const { data: filterBankState, loading: stateLoading } = useFilterBankState({
    subscribe: true,
  });
  const { assign: switchFilter, isLoading: isSwitching } = useSwitchFilter();
  const { assign: toggleFilter, isLoading: isToggling } = useToggleFilter();

  const filters = filterBankState?.filters ?? [];
  const currentSlot = filterBankState?.current_slot;

  const handleSelectFilter = (slot: number) => {
    if (slot !== currentSlot) {
      switchFilter({ slot });
    }
  };

  const handleToggle = () => {
    toggleFilter({});
  };

  const isLoading = isSwitching || isToggling;

  return (
    <div className="space-y-4">
      {/* Filters */}
      <ResponsiveGrid>
        {filters.map((filter) => {
          const isActive = filter.slot === currentSlot;

          return (
            <div
              key={filter.slot}
              className={cn(
                "@container min-w-0 overflow-hidden cursor-pointer rounded-lg border p-3 transition-all",
                isActive
                  ? "bg-primary/5 border-primary/30"
                  : "bg-muted/30 border-transparent hover:bg-muted/50",
              )}
              onClick={() => handleSelectFilter(filter.slot)}
            >
              {/* Filter Header */}
              <div className="flex flex-col gap-2 @[280px]:flex-row @[280px]:items-start @[280px]:justify-between">
                <div className="flex min-w-0 items-center gap-2">
                  <TooltipProvider>
                    <Tooltip>
                      <TooltipTrigger>
                        <div
                          className={cn(
                            "w-3 h-3 rounded-full",
                            getWavelengthColor(filter.center_wavelength),
                            isActive && "animate-pulse",
                          )}
                        />
                      </TooltipTrigger>
                      <TooltipContent>
                        <p>{filter.center_wavelength}nm</p>
                      </TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                  <span className="truncate text-sm font-medium">
                    {filter.name}
                  </span>
                  <span
                    className={cn(
                      "hidden text-xs font-mono @[320px]:inline",
                      getWavelengthTextColor(filter.center_wavelength),
                    )}
                  >
                    {filter.center_wavelength}nm
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <Switch
                    checked={isActive}
                    onCheckedChange={() => handleSelectFilter(filter.slot)}
                    disabled={isLoading}
                    onClick={(e) => e.stopPropagation()}
                  />
                </div>
              </div>

              {/* Filter Details */}
              <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-muted-foreground @[360px]:grid-cols-3">
                <span className="text-xs text-muted-foreground">
                  BW: {filter.bandwidth}nm
                </span>
                <span className="text-xs text-muted-foreground">
                  T: {(filter.transmission * 100).toFixed(0)}%
                </span>
                <span className="hidden text-xs text-muted-foreground @[360px]:inline">
                  {t("common.slot", { slot: filter.slot })}
                </span>
              </div>
            </div>
          );
        })}

        {(!filters || filters.length === 0) && !stateLoading && (
          <div className="text-center py-4 text-sm text-muted-foreground col-span-full">
            {t("microscope.noFilters")}
          </div>
        )}
      </ResponsiveGrid>

      {/* Quick Toggle Button */}
      {filters.length > 1 && (
        <Button
          variant="outline"
          size="sm"
          className="w-full gap-2"
          onClick={handleToggle}
          disabled={isLoading}
        >
          <RotateCw className={cn("h-4 w-4", isToggling && "animate-spin")} />
          {t("microscope.nextFilter")}
        </Button>
      )}
    </div>
  );
}
