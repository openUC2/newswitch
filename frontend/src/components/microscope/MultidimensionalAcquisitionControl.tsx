import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  AcquireMultidimensionalAcquisitionArgsSchema,
  useAcquireMultidimensionalAcquisition,
  type AcquireMultidimensionalAcquisitionArgs,
  type Illumination,
  type Position,
  type Stack,
  type Streams,
  type Timepoint,
} from "@/apps/default/hooks/actions";
import {
  useCameraState,
  useIlluminationState,
  useStageState,
} from "@/apps/default/hooks/states";
import { cn } from "@/lib/utils";
import { usePauseTask } from "@/apps/default/hooks/usePauseTask";
import { useResumeTask } from "@/apps/default/hooks/useResumeTask";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  ChevronDown,
  ChevronRight,
  Clock,
  Copy,
  Crosshair,
  Grid3X3,
  Layers,
  MapPin,
  Pause,
  Play,
  Plus,
  RotateCcw,
  Square,
  Trash2,
} from "lucide-react";
import { useCallback, useState } from "react";
import { useFieldArray, useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";

// ---------------------------------------------------------------------------
// Helpers – z_slices is number[] in the schema, but we edit as comma string
// ---------------------------------------------------------------------------

function zSlicesToString(slices: number[]): string {
  return slices.join(", ");
}

function stringToZSlices(raw: string): number[] {
  return raw
    .split(",")
    .map((s) => parseFloat(s.trim()))
    .filter((n) => !isNaN(n));
}

// ---------------------------------------------------------------------------
// Default factories from live state
// ---------------------------------------------------------------------------

function makeDefaultIllumination(): Illumination {
  return { source: "LED1", wavelength: 488, intensity: 0.8 };
}

function makeDefaultStream(): Streams {
  return {
    detector: "camera_1",
    mapping: "default",
    illuminations: [makeDefaultIllumination()],
  };
}

function makeDefaultStack(channels?: Streams[]): Stack {
  return {
    z_offset: 0,
    z_step: 1,
    z_slices: [-5, -3, -1, 0, 1, 3, 5],
    channels: channels ?? [makeDefaultStream()],
    z_hooks: [],
  };
}

function makeDefaultPosition(
  x = 0,
  y = 0,
  z = 0,
  channels?: Streams[],
): Position {
  return {
    x,
    y,
    z,
    stacks: [makeDefaultStack(channels)],
    p_hooks: [],
  };
}

function makeDefaultTimepoint(positions?: Position[]): Timepoint {
  return {
    time: undefined,
    position_order: "sequential",
    positions: positions ?? [makeDefaultPosition()],
    t_hooks: [],
  };
}

function makeDefaultConfig(
  positions?: Position[],
): AcquireMultidimensionalAcquisitionArgs {
  return {
    config: {
      timepoints: [makeDefaultTimepoint(positions)],
      file_name: "acquisition_001",
      file_format: "tiff",
      m_hooks: [],
    },
  };
}

// Type alias for the form
type FormValues = AcquireMultidimensionalAcquisitionArgs;

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function MultidimensionalAcquisitionControl() {
  const { t } = useTranslation();
  const [selectedTimepoint, setSelectedTimepoint] = useState(0);
  const [selectedPosition, setSelectedPosition] = useState(0);
  const [expandedSection, setExpandedSection] = useState<string | null>(
    "timepoints",
  );

  // Live microscope state
  const { data: cameraState } = useCameraState({ subscribe: true });
  const { data: illuminationState } = useIlluminationState({ subscribe: true });
  const { data: stageState } = useStageState({ subscribe: true });

  // Acquisition action
  const {
    assign: startAcquisition,
    isLoading,
    task,
    progress,
    cancel,
  } = useAcquireMultidimensionalAcquisition();

  // Pause/Resume
  const pause = usePauseTask();
  const resume = useResumeTask();

  // Build channels from current microscope state
  const buildChannelsFromState = useCallback((): Streams[] => {
    const detectors = cameraState?.detectors ?? [];
    const activeDetectors = detectors.filter((d) => d.is_active);
    const illuminations = illuminationState?.illuminations ?? [];
    const activeIlluminations = illuminations.filter((i) => i.is_active);

    if (activeDetectors.length === 0) {
      return [makeDefaultStream()];
    }

    return activeDetectors.map((det) => ({
      detector: det.name,
      mapping: det.current_colormap || "default",
      illuminations:
        activeIlluminations.length > 0
          ? activeIlluminations.map((ill) => ({
              source: ill.kind ?? `slot_${ill.slot}`,
              wavelength: ill.wavelength ?? 488,
              intensity: ill.intensity / (ill.max_intensity || 100),
            }))
          : [makeDefaultIllumination()],
    }));
  }, [cameraState, illuminationState]);

  // Build position from current state
  const buildPositionFromState = useCallback((): Position => {
    return makeDefaultPosition(
      stageState?.x ?? 0,
      stageState?.y ?? 0,
      stageState?.z ?? 0,
      buildChannelsFromState(),
    );
  }, [stageState, buildChannelsFromState]);

  // Build defaults from current microscope state
  const buildDefaultsFromState = useCallback((): FormValues => {
    const pos = buildPositionFromState();
    return makeDefaultConfig([pos]);
  }, [buildPositionFromState]);

  const form = useForm<FormValues>({
    resolver: zodResolver(AcquireMultidimensionalAcquisitionArgsSchema),
    defaultValues: buildDefaultsFromState(),
  });

  const timepointsField = useFieldArray({
    control: form.control,
    name: "config.timepoints",
  });

  // Ensure indices stay valid
  const safeTP = Math.min(
    selectedTimepoint,
    Math.max(0, timepointsField.fields.length - 1),
  );
  const positions = form.watch(`config.timepoints.${safeTP}.positions`) ?? [];
  const safePos = Math.min(selectedPosition, Math.max(0, positions.length - 1));

  // ---------------------------------------------------------------------------
  // Actions
  // ---------------------------------------------------------------------------

  // Add a new timepoint with default config
  const addTimepoint = () => {
    const pos = buildPositionFromState();
    timepointsField.append(makeDefaultTimepoint([pos]));
    setSelectedTimepoint(timepointsField.fields.length);
    setSelectedPosition(0);
  };

  // Copy current timepoint's positions to a new timepoint
  const copyCurrentTimepointToNew = () => {
    const currentTP = form.getValues(`config.timepoints.${safeTP}`);
    if (currentTP) {
      // Deep clone the positions
      const clonedPositions = JSON.parse(JSON.stringify(currentTP.positions));
      timepointsField.append({
        ...makeDefaultTimepoint(),
        positions: clonedPositions,
      });
      setSelectedTimepoint(timepointsField.fields.length);
      setSelectedPosition(0);
    }
  };

  const removeTimepoint = (index: number) => {
    if (timepointsField.fields.length <= 1) return;
    timepointsField.remove(index);
    if (selectedTimepoint >= timepointsField.fields.length - 1) {
      setSelectedTimepoint(Math.max(0, timepointsField.fields.length - 2));
    }
    setSelectedPosition(0);
  };

  // Add position from current stage + channels state
  const addPositionFromCurrentState = () => {
    const pos = buildPositionFromState();
    const currentPositions =
      form.getValues(`config.timepoints.${safeTP}.positions`) ?? [];
    form.setValue(`config.timepoints.${safeTP}.positions`, [
      ...currentPositions,
      pos,
    ]);
    setSelectedPosition(currentPositions.length);
  };

  const removePosition = (posIdx: number) => {
    const arr = form.getValues(`config.timepoints.${safeTP}.positions`);
    if (arr.length <= 1) return;
    arr.splice(posIdx, 1);
    form.setValue(`config.timepoints.${safeTP}.positions`, arr);
    setSelectedPosition(Math.min(safePos, arr.length - 1));
  };

  const handleInitFromState = () => {
    form.reset(buildDefaultsFromState());
    setSelectedTimepoint(0);
    setSelectedPosition(0);
  };

  const onSubmit = (data: FormValues) => {
    startAcquisition(data, { notify: true });
  };

  const handleCancel = () => {
    if (task?.id) cancel();
  };

  const totalPositions = timepointsField.fields.reduce((acc, _, idx) => {
    const tpPositions = form.watch(`config.timepoints.${idx}.positions`) ?? [];
    return acc + tpPositions.length;
  }, 0);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Grid3X3 className="h-4 w-4" />
          <span className="text-sm font-medium">
            {t("acquisition.experiment")}
          </span>
        </div>
        <Badge variant="outline" className="text-xs">
          {timepointsField.fields.length} T × {totalPositions} P
        </Badge>
      </div>

      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-3">
          {/* File settings */}
          <div className="flex gap-2">
            <FormField
              control={form.control}
              name="config.file_name"
              render={({ field }) => (
                <FormItem className="flex-1">
                  <FormControl>
                    <Input
                      {...field}
                      placeholder="acquisition_001"
                      className="h-8 text-sm"
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="config.file_format"
              render={({ field }) => (
                <FormItem className="w-20">
                  <FormControl>
                    <Input
                      {...field}
                      placeholder="tiff"
                      className="h-8 text-sm"
                    />
                  </FormControl>
                </FormItem>
              )}
            />
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    className="h-8 w-8 shrink-0"
                    onClick={handleInitFromState}
                  >
                    <RotateCcw className="h-3.5 w-3.5" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>
                  {t("acquisition.resetFromState")}
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>

          {/* Timepoints Section */}
          <Collapsible
            open={expandedSection === "timepoints"}
            onOpenChange={(open) =>
              setExpandedSection(open ? "timepoints" : null)
            }
          >
            <CollapsibleTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                className="w-full justify-between h-8 px-2"
              >
                <div className="flex items-center gap-2">
                  <Clock className="h-3.5 w-3.5" />
                  <span className="text-xs font-medium">
                    {t("acquisition.timepoints")}
                  </span>
                  <Badge variant="secondary" className="h-5 text-[10px]">
                    {timepointsField.fields.length}
                  </Badge>
                </div>
                <ChevronDown
                  className={cn(
                    "h-4 w-4 transition-transform",
                    expandedSection === "timepoints" && "rotate-180",
                  )}
                />
              </Button>
            </CollapsibleTrigger>
            <CollapsibleContent className="pt-2 space-y-2">
              <ScrollArea className="max-h-32">
                <div className="space-y-1">
                  {timepointsField.fields.map((field, tpIdx) => {
                    const tpPositions =
                      form.watch(`config.timepoints.${tpIdx}.positions`) ?? [];
                    return (
                      <div
                        key={field.id}
                        className={cn(
                          "group flex items-center justify-between px-2 py-1.5 rounded text-sm cursor-pointer transition-colors",
                          "hover:bg-accent",
                          tpIdx === safeTP && "bg-accent font-medium",
                        )}
                        onClick={() => {
                          setSelectedTimepoint(tpIdx);
                          setSelectedPosition(0);
                        }}
                      >
                        <div className="flex items-center gap-2">
                          <Clock className="h-3 w-3 text-muted-foreground" />
                          <span className="text-xs">T{tpIdx + 1}</span>
                          <span className="text-[10px] text-muted-foreground">
                            (
                            {t("acquisition.positionCount", {
                              count: tpPositions.length,
                            })}
                            )
                          </span>
                        </div>
                        {timepointsField.fields.length > 1 && (
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="h-5 w-5 opacity-0 group-hover:opacity-100"
                            onClick={(e) => {
                              e.stopPropagation();
                              removeTimepoint(tpIdx);
                            }}
                          >
                            <Trash2 className="h-3 w-3 text-destructive" />
                          </Button>
                        )}
                      </div>
                    );
                  })}
                </div>
              </ScrollArea>
              <div className="flex gap-1">
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="flex-1 h-7 text-xs gap-1"
                        onClick={addTimepoint}
                      >
                        <Plus className="h-3 w-3" />
                        {t("acquisition.newTimepoint")}
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>
                      {t("acquisition.addTimepoint")}
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="flex-1 h-7 text-xs gap-1"
                        onClick={copyCurrentTimepointToNew}
                      >
                        <Copy className="h-3 w-3" />
                        {t("acquisition.copyTimepoint", {
                          timepoint: safeTP + 1,
                        })}
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>
                      {t("acquisition.copyTimepointDescription")}
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
            </CollapsibleContent>
          </Collapsible>

          {/* Positions Section */}
          <Collapsible
            open={expandedSection === "positions"}
            onOpenChange={(open) =>
              setExpandedSection(open ? "positions" : null)
            }
          >
            <CollapsibleTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                className="w-full justify-between h-8 px-2"
              >
                <div className="flex items-center gap-2">
                  <MapPin className="h-3.5 w-3.5" />
                  <span className="text-xs font-medium">
                    {t("acquisition.positions", { timepoint: safeTP + 1 })}
                  </span>
                  <Badge variant="secondary" className="h-5 text-[10px]">
                    {positions.length}
                  </Badge>
                </div>
                <ChevronDown
                  className={cn(
                    "h-4 w-4 transition-transform",
                    expandedSection === "positions" && "rotate-180",
                  )}
                />
              </Button>
            </CollapsibleTrigger>
            <CollapsibleContent className="pt-2 space-y-2">
              <ScrollArea className="max-h-40">
                <div className="space-y-1">
                  {positions.map((pos, posIdx) => (
                    <div
                      key={posIdx}
                      className={cn(
                        "group flex items-center justify-between px-2 py-1.5 rounded text-sm cursor-pointer transition-colors",
                        "hover:bg-accent",
                        posIdx === safePos && "bg-accent font-medium",
                      )}
                      onClick={() => setSelectedPosition(posIdx)}
                    >
                      <div className="flex items-center gap-2">
                        <MapPin className="h-3 w-3 text-muted-foreground" />
                        <span className="text-xs">P{posIdx + 1}</span>
                        <span className="text-[10px] text-muted-foreground font-mono">
                          ({pos.x?.toFixed(0)}, {pos.y?.toFixed(0)},{" "}
                          {pos.z?.toFixed(0)})
                        </span>
                      </div>
                      {positions.length > 1 && (
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          className="h-5 w-5 opacity-0 group-hover:opacity-100"
                          onClick={(e) => {
                            e.stopPropagation();
                            removePosition(posIdx);
                          }}
                        >
                          <Trash2 className="h-3 w-3 text-destructive" />
                        </Button>
                      )}
                    </div>
                  ))}
                </div>
              </ScrollArea>
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="w-full h-7 text-xs gap-1"
                      onClick={addPositionFromCurrentState}
                    >
                      <Crosshair className="h-3 w-3" />
                      {t("acquisition.addCurrentPosition")}
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>
                    {t("acquisition.addCurrentPositionDescription")}
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            </CollapsibleContent>
          </Collapsible>

          {/* Selected Position Detail */}
          {positions.length > 0 && (
            <Collapsible
              open={expandedSection === "detail"}
              onOpenChange={(open) =>
                setExpandedSection(open ? "detail" : null)
              }
            >
              <CollapsibleTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  className="w-full justify-between h-8 px-2"
                >
                  <div className="flex items-center gap-2">
                    <Layers className="h-3.5 w-3.5" />
                    <span className="text-xs font-medium">
                      {t("acquisition.positionDetails", {
                        position: safePos + 1,
                      })}
                    </span>
                  </div>
                  <ChevronDown
                    className={cn(
                      "h-4 w-4 transition-transform",
                      expandedSection === "detail" && "rotate-180",
                    )}
                  />
                </Button>
              </CollapsibleTrigger>
              <CollapsibleContent className="pt-2">
                <PositionEditor
                  control={form.control}
                  timepointIndex={safeTP}
                  positionIndex={safePos}
                />
              </CollapsibleContent>
            </Collapsible>
          )}

          <Separator />

          {/* Task Progress & Status */}
          {(isLoading || task) && (
            <div className="space-y-2 p-3 bg-muted/50 rounded-lg">
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">
                  {task?.status === "paused"
                    ? t("acquisition.paused")
                    : t("acquisition.acquiring")}
                </span>
                <div className="flex items-center gap-2">
                  {progress !== null && progress !== undefined && (
                    <span className="font-mono font-semibold">
                      {Math.round(progress)}%
                    </span>
                  )}
                  {task && (
                    <Badge
                      variant={
                        task.status === "completed" ? "default" : "secondary"
                      }
                      className="text-[10px]"
                    >
                      {t(`taskStatus.${task.status}`)}
                    </Badge>
                  )}
                </div>
              </div>
              {progress !== null && (
                <Progress value={progress} className="h-1.5" />
              )}
            </div>
          )}

          {/* Action buttons */}
          <div className="flex gap-2">
            {isLoading ? (
              <>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="flex-1 h-9"
                  onClick={handleCancel}
                >
                  <Square className="h-3.5 w-3.5 mr-1.5" />
                  {t("common.cancel")}
                </Button>
                {task?.status === "paused" ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="flex-1 h-9 animate-pulse"
                    onClick={() => task?.id && resume(task.id)}
                  >
                    <Play className="h-3.5 w-3.5 mr-1.5" />
                    {t("microscope.resume")}
                  </Button>
                ) : (
                  <Button
                    type="button"
                    variant="destructive"
                    size="sm"
                    className="flex-1 h-9"
                    onClick={() => task?.id && pause(task.id)}
                  >
                    <Pause className="h-3.5 w-3.5 mr-1.5" />
                    {t("microscope.pause")}
                  </Button>
                )}
              </>
            ) : (
              <Button type="submit" size="sm" className="flex-1 h-9">
                <Play className="h-3.5 w-3.5 mr-1.5" />
                {t("acquisition.start")}
              </Button>
            )}
          </div>
        </form>
      </Form>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-component: Position editor (compact)
// ---------------------------------------------------------------------------

function PositionEditor({
  control,
  timepointIndex,
  positionIndex,
}: {
  control: ReturnType<typeof useForm<FormValues>>["control"];
  timepointIndex: number;
  positionIndex: number;
}) {
  const { t } = useTranslation();
  const stacksField = useFieldArray({
    control,
    name: `config.timepoints.${timepointIndex}.positions.${positionIndex}.stacks`,
  });

  return (
    <div className="space-y-3">
      {/* XYZ */}
      <div className="grid grid-cols-3 gap-2">
        {(["x", "y", "z"] as const).map((axis) => (
          <FormField
            key={axis}
            control={control}
            name={`config.timepoints.${timepointIndex}.positions.${positionIndex}.${axis}`}
            render={({ field }) => (
              <FormItem>
                <FormLabel className="text-[10px] uppercase">
                  {axis} (µm)
                </FormLabel>
                <FormControl>
                  <Input
                    type="number"
                    step="any"
                    value={field.value}
                    onChange={(e) =>
                      field.onChange(parseFloat(e.target.value) || 0)
                    }
                    className="h-7 text-xs"
                  />
                </FormControl>
              </FormItem>
            )}
          />
        ))}
      </div>

      {/* Stacks */}
      {stacksField.fields.map((stackField, stackIdx) => (
        <StackEditor
          key={stackField.id}
          control={control}
          timepointIndex={timepointIndex}
          positionIndex={positionIndex}
          stackIndex={stackIdx}
          canRemove={stacksField.fields.length > 1}
          onRemove={() => stacksField.remove(stackIdx)}
        />
      ))}

      <Button
        type="button"
        variant="outline"
        size="sm"
        className="w-full h-7 text-xs gap-1"
        onClick={() => stacksField.append(makeDefaultStack())}
      >
        <Plus className="h-3 w-3" />
        {t("acquisition.addStack")}
      </Button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-component: Stack editor (compact)
// ---------------------------------------------------------------------------

function StackEditor({
  control,
  timepointIndex,
  positionIndex,
  stackIndex,
  canRemove,
  onRemove,
}: {
  control: ReturnType<typeof useForm<FormValues>>["control"];
  timepointIndex: number;
  positionIndex: number;
  stackIndex: number;
  canRemove: boolean;
  onRemove: () => void;
}) {
  const { t } = useTranslation();
  const channelsField = useFieldArray({
    control,
    name: `config.timepoints.${timepointIndex}.positions.${positionIndex}.stacks.${stackIndex}.channels`,
  });

  const stackBase =
    `config.timepoints.${timepointIndex}.positions.${positionIndex}.stacks.${stackIndex}` as const;

  return (
    <div className="rounded-lg border p-2 space-y-2 bg-muted/20">
      <div className="flex items-center justify-between">
        <h4 className="text-[10px] font-semibold flex items-center gap-1">
          <Layers className="h-3 w-3" />
          {t("acquisition.stack", { stack: stackIndex + 1 })}
        </h4>
        {canRemove && (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-5 w-5"
            onClick={onRemove}
          >
            <Trash2 className="h-3 w-3 text-destructive" />
          </Button>
        )}
      </div>

      {/* Z params */}
      <div className="grid grid-cols-3 gap-1.5">
        <FormField
          control={control}
          name={`${stackBase}.z_offset`}
          render={({ field }) => (
            <FormItem>
              <FormLabel className="text-[10px]">
                {t("acquisition.offset")}
              </FormLabel>
              <FormControl>
                <Input
                  type="number"
                  step="any"
                  value={field.value}
                  onChange={(e) =>
                    field.onChange(parseFloat(e.target.value) || 0)
                  }
                  className="h-6 text-[10px]"
                />
              </FormControl>
            </FormItem>
          )}
        />
        <FormField
          control={control}
          name={`${stackBase}.z_step`}
          render={({ field }) => (
            <FormItem>
              <FormLabel className="text-[10px]">
                {t("acquisition.step")}
              </FormLabel>
              <FormControl>
                <Input
                  type="number"
                  step="0.1"
                  min="0.01"
                  value={field.value}
                  onChange={(e) =>
                    field.onChange(parseFloat(e.target.value) || 1)
                  }
                  className="h-6 text-[10px]"
                />
              </FormControl>
            </FormItem>
          )}
        />
        <FormField
          control={control}
          name={`${stackBase}.z_slices`}
          render={({ field }) => (
            <FormItem>
              <FormLabel className="text-[10px]">
                {t("acquisition.slices")}
              </FormLabel>
              <FormControl>
                <Input
                  value={zSlicesToString(field.value ?? [])}
                  onChange={(e) =>
                    field.onChange(stringToZSlices(e.target.value))
                  }
                  placeholder="-5,0,5"
                  className="h-6 text-[10px]"
                />
              </FormControl>
            </FormItem>
          )}
        />
      </div>

      {/* Channels */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <span className="text-[10px] font-medium text-muted-foreground">
            {t("acquisition.channels")}
          </span>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-5 text-[10px] px-1 gap-0.5"
            onClick={() => channelsField.append(makeDefaultStream())}
          >
            <Plus className="h-2.5 w-2.5" />
          </Button>
        </div>

        {channelsField.fields.map((chField, chIdx) => (
          <ChannelEditor
            key={chField.id}
            control={control}
            timepointIndex={timepointIndex}
            positionIndex={positionIndex}
            stackIndex={stackIndex}
            channelIndex={chIdx}
            canRemove={channelsField.fields.length > 1}
            onRemove={() => channelsField.remove(chIdx)}
          />
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-component: Channel (stream) editor (compact)
// ---------------------------------------------------------------------------

function ChannelEditor({
  control,
  timepointIndex,
  positionIndex,
  stackIndex,
  channelIndex,
  canRemove,
  onRemove,
}: {
  control: ReturnType<typeof useForm<FormValues>>["control"];
  timepointIndex: number;
  positionIndex: number;
  stackIndex: number;
  channelIndex: number;
  canRemove: boolean;
  onRemove: () => void;
}) {
  const { t } = useTranslation();
  const basePath =
    `config.timepoints.${timepointIndex}.positions.${positionIndex}.stacks.${stackIndex}.channels.${channelIndex}` as const;

  const illuminationsField = useFieldArray({
    control,
    name: `config.timepoints.${timepointIndex}.positions.${positionIndex}.stacks.${stackIndex}.channels.${channelIndex}.illuminations`,
  });

  const [expanded, setExpanded] = useState(false);

  return (
    <div className="rounded border p-1.5 space-y-1 bg-background/50">
      <div className="flex gap-1.5 items-center">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-5 w-5 shrink-0"
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? (
            <ChevronDown className="h-3 w-3" />
          ) : (
            <ChevronRight className="h-3 w-3" />
          )}
        </Button>
        <FormField
          control={control}
          name={`${basePath}.detector`}
          render={({ field }) => (
            <FormItem className="flex-1">
              <FormControl>
                <Input
                  {...field}
                  placeholder={t("acquisition.detector")}
                  className="h-6 text-[10px]"
                />
              </FormControl>
            </FormItem>
          )}
        />
        <FormField
          control={control}
          name={`${basePath}.mapping`}
          render={({ field }) => (
            <FormItem className="w-16">
              <FormControl>
                <Input
                  {...field}
                  placeholder={t("acquisition.mapping")}
                  className="h-6 text-[10px]"
                />
              </FormControl>
            </FormItem>
          )}
        />
        {canRemove && (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-5 w-5 shrink-0"
            onClick={onRemove}
          >
            <Trash2 className="h-3 w-3 text-destructive" />
          </Button>
        )}
      </div>

      {/* Illuminations (expanded) */}
      {expanded && (
        <div className="pl-6 space-y-1">
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-muted-foreground">
              {t("acquisition.illuminations")}
            </span>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-4 text-[10px] px-1"
              onClick={() =>
                illuminationsField.append(makeDefaultIllumination())
              }
            >
              <Plus className="h-2.5 w-2.5" />
            </Button>
          </div>
          {illuminationsField.fields.map((illField, illIdx) => (
            <div key={illField.id} className="flex gap-1 items-end">
              <FormField
                control={control}
                name={`${basePath}.illuminations.${illIdx}.source`}
                render={({ field }) => (
                  <FormItem className="flex-1">
                    <FormControl>
                      <Input
                        {...field}
                        placeholder={t("acquisition.source")}
                        className="h-5 text-[10px]"
                      />
                    </FormControl>
                  </FormItem>
                )}
              />
              <FormField
                control={control}
                name={`${basePath}.illuminations.${illIdx}.wavelength`}
                render={({ field }) => (
                  <FormItem className="w-12">
                    <FormControl>
                      <Input
                        type="number"
                        value={field.value}
                        onChange={(e) =>
                          field.onChange(parseFloat(e.target.value) || 0)
                        }
                        placeholder="λ"
                        className="h-5 text-[10px]"
                      />
                    </FormControl>
                  </FormItem>
                )}
              />
              <FormField
                control={control}
                name={`${basePath}.illuminations.${illIdx}.intensity`}
                render={({ field }) => (
                  <FormItem className="w-10">
                    <FormControl>
                      <Input
                        type="number"
                        step="0.05"
                        min="0"
                        max="1"
                        value={field.value}
                        onChange={(e) =>
                          field.onChange(parseFloat(e.target.value) || 0)
                        }
                        placeholder={t("acquisition.intensity")}
                        className="h-5 text-[10px]"
                      />
                    </FormControl>
                  </FormItem>
                )}
              />
              {illuminationsField.fields.length > 1 && (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-5 w-5 shrink-0"
                  onClick={() => illuminationsField.remove(illIdx)}
                >
                  <Trash2 className="h-2.5 w-2.5 text-destructive" />
                </Button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
