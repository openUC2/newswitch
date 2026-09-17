import { ActionButton } from "@/components/ActionButton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  MoveHomeDefinition,
  MoveStageDefinition,
} from "@/apps/default/hooks/actions";
import { useStagePositionLock } from "@/apps/default/hooks/locks";
import { useStageState } from "@/apps/default/hooks/states";
import { cn } from "@/lib/utils";
import {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  Home,
  Move,
  RotateCcw,
} from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { ProgressDisplay } from "../TaskDisplay";

export function StageControl() {
  const { t, i18n } = useTranslation();
  const formatNumber = (value: number, digits: number) =>
    new Intl.NumberFormat(i18n.resolvedLanguage, {
      maximumFractionDigits: digits,
      minimumFractionDigits: digits,
    }).format(value);
  const { data: stageState, loading: stateLoading } = useStageState({
    subscribe: true,
  });

  const activeTaskId = useStagePositionLock().lockingTaskId;

  // Use registered step sizes from state, or fallback
  const stepSizes = stageState?.registered_step_sizes?.length
    ? stageState.registered_step_sizes
    : [1, 10, 100, 1000];

  const [stepSize, setStepSize] = useState(stepSizes[1] ?? 10);
  const [zStep, setZStep] = useState(10);
  const [targetX, setTargetX] = useState("");
  const [targetY, setTargetY] = useState("");
  const [targetZ, setTargetZ] = useState("");

  // Calculate position percentages for visual indicators
  const getPositionPercent = (
    value: number | undefined,
    min: number | undefined,
    max: number | undefined,
  ) => {
    if (value === undefined || min === undefined || max === undefined)
      return 50;
    const range = max - min;
    if (range <= 0) return 50;
    return ((value - min) / range) * 100;
  };

  const xPercent = getPositionPercent(
    stageState?.x,
    stageState?.min_x,
    stageState?.max_x,
  );
  const yPercent = getPositionPercent(
    stageState?.y,
    stageState?.min_y,
    stageState?.max_y,
  );
  const zPercent = getPositionPercent(
    stageState?.z,
    stageState?.min_z,
    stageState?.max_z,
  );

  return (
    <div className="w-full space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Move className="h-4 w-4" />
          <span className="text-sm font-medium">
            {t("microscope.stageControl")}
          </span>
        </div>
        {stateLoading && (
          <Badge variant="outline" className="text-xs">
            {t("common.loading")}
          </Badge>
        )}
      </div>

      {/* Current Position Display */}
      <div className="grid grid-cols-4 gap-2">
        {[
          {
            label: "X",
            value: stageState?.x,
            percent: xPercent,
            unit: "µm",
            color: "bg-red-500",
          },
          {
            label: "Y",
            value: stageState?.y,
            percent: yPercent,
            unit: "µm",
            color: "bg-green-500",
          },
          {
            label: "Z",
            value: stageState?.z,
            percent: zPercent,
            unit: "µm",
            color: "bg-blue-500",
          },
          {
            label: "A",
            value: stageState?.a,
            percent: null,
            unit: "°",
            color: "bg-purple-500",
          },
        ].map((axis) => (
          <TooltipProvider key={axis.label}>
            <Tooltip>
              <TooltipTrigger asChild>
                <div className="p-2 bg-muted/50 rounded-lg text-center relative overflow-hidden">
                  {axis.percent !== null && (
                    <div
                      className={cn(
                        "absolute bottom-0 left-0 h-1 transition-all",
                        axis.color,
                      )}
                      style={{ width: `${axis.percent}%` }}
                    />
                  )}
                  <div className="text-xs text-muted-foreground uppercase">
                    {axis.label}
                  </div>
                  <div className="text-sm font-mono font-bold">
                    {stateLoading
                      ? "..."
                      : axis.value === undefined
                        ? "—"
                        : formatNumber(axis.value, 1)}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {axis.unit}
                  </div>
                </div>
              </TooltipTrigger>
              <TooltipContent>
                <p>
                  {axis.label}:{" "}
                  {axis.value === undefined ? "—" : formatNumber(axis.value, 3)}{" "}
                  {axis.unit}
                </p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        ))}
      </div>

      {/* XY Joystick Controls */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-xs text-muted-foreground">
            {t("microscope.xyMovement")}
          </span>
          <div className="flex gap-1">
            {stepSizes.slice(0, 4).map((size) => (
              <Button
                key={size}
                size="sm"
                variant={stepSize === size ? "default" : "outline"}
                onClick={() => setStepSize(size)}
                className="h-7 px-2 text-xs"
              >
                {size >= 1000 ? `${size / 1000}mm` : `${size}µm`}
              </Button>
            ))}
          </div>
        </div>

        <div className="flex justify-center">
          <div className="grid grid-cols-3 gap-1">
            <div />
            <ActionButton
              action={MoveStageDefinition}
              args={{ y: stepSize, is_absolute: false }}
              variant="outline"
              size="icon"
              className="h-10 w-10"
            >
              <ArrowUp className="h-5 w-5" />
            </ActionButton>
            <div />
            <ActionButton
              action={MoveStageDefinition}
              args={{ x: -stepSize, is_absolute: false }}
              variant="outline"
              size="icon"
              className="h-10 w-10"
            >
              <ArrowLeft className="h-5 w-5" />
            </ActionButton>
            <ActionButton
              action={MoveHomeDefinition}
              args={{}}
              variant="secondary"
              size="icon"
              className="h-10 w-10"
            >
              <Home className="h-4 w-4" />
            </ActionButton>
            <ActionButton
              action={MoveStageDefinition}
              args={{ x: stepSize, is_absolute: false }}
              variant="outline"
              size="icon"
              className="h-10 w-10"
            >
              <ArrowRight className="h-5 w-5" />
            </ActionButton>
            <div />
            <ActionButton
              action={MoveStageDefinition}
              args={{ y: -stepSize, is_absolute: false }}
              variant="outline"
              size="icon"
              className="h-10 w-10"
            >
              <ArrowDown className="h-5 w-5" />
            </ActionButton>
            <div />
          </div>
        </div>
      </div>

      {/* Z Control */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-xs text-muted-foreground">
            {t("microscope.focus")}
          </span>
          <div className="flex items-center gap-1">
            <Input
              type="number"
              value={zStep}
              onChange={(e) => setZStep(parseFloat(e.target.value) || 10)}
              className="w-16 h-7 text-xs"
            />
            <span className="text-xs text-muted-foreground">µm</span>
          </div>
        </div>
        <div className="flex gap-2">
          <ActionButton
            action={MoveStageDefinition}
            args={{ z: zStep, is_absolute: false }}
            variant="outline"
            className="flex-1 h-9"
          >
            <ArrowUp className="h-3 w-3 mr-1" />
            {t("microscope.up")}
          </ActionButton>
          <ActionButton
            action={MoveStageDefinition}
            args={{ z: -zStep, is_absolute: false }}
            variant="outline"
            className="flex-1 h-9"
          >
            <ArrowDown className="h-3 w-3 mr-1" />
            {t("microscope.down")}
          </ActionButton>
        </div>
      </div>

      {/* Absolute Position */}
      <div className="space-y-2 pt-2 border-t border-border/50">
        <span className="text-xs text-muted-foreground">
          {t("microscope.goToPosition")}
        </span>
        <div className="grid grid-cols-3 gap-2">
          <div className="space-y-1">
            <span className="text-xs text-muted-foreground">X</span>
            <Input
              type="number"
              placeholder={stageState?.x?.toFixed(0)}
              value={targetX}
              onChange={(e) => setTargetX(e.target.value)}
              className="h-8 text-xs"
            />
          </div>
          <div className="space-y-1">
            <span className="text-xs text-muted-foreground">Y</span>
            <Input
              type="number"
              placeholder={stageState?.y?.toFixed(0)}
              value={targetY}
              onChange={(e) => setTargetY(e.target.value)}
              className="h-8 text-xs"
            />
          </div>
          <div className="space-y-1">
            <span className="text-xs text-muted-foreground">Z</span>
            <Input
              type="number"
              placeholder={stageState?.z?.toFixed(0)}
              value={targetZ}
              onChange={(e) => setTargetZ(e.target.value)}
              className="h-8 text-xs"
            />
          </div>
        </div>
        <ActionButton
          action={MoveStageDefinition}
          args={{
            x: targetX ? parseFloat(targetX) : undefined,
            y: targetY ? parseFloat(targetY) : undefined,
            z: targetZ ? parseFloat(targetZ) : undefined,
            is_absolute: true,
          }}
          disabled={!targetX && !targetY && !targetZ}
          className="w-full h-8"
          variant="secondary"
        >
          <RotateCcw className="h-3 w-3 mr-1" />
          {t("microscope.move")}
        </ActionButton>
      </div>

      <ProgressDisplay activeTaskId={activeTaskId} />
    </div>
  );
}
