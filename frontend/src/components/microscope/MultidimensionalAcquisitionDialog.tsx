import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
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
  type StageState,
} from "@/apps/default/hooks/states";
import { cn } from "@/lib/utils";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  ChevronRight,
  Clock,
  Grid3X3,
  Layers,
  MapPin,
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

// Type alias for the form – it IS the generated args type directly
type FormValues = AcquireMultidimensionalAcquisitionArgs;

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function MultidimensionalAcquisitionDialog() {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [selectedTimepoint, setSelectedTimepoint] = useState(0);
  const [selectedPosition, setSelectedPosition] = useState(0);

  // Live microscope state for "init from state"
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

  // Build defaults from current microscope state
  const buildDefaultsFromState = useCallback((): FormValues => {
    const detectors = cameraState?.detectors ?? [];
    const activeDetectors = detectors.filter((d) => d.is_active);
    const illuminations = illuminationState?.illuminations ?? [];
    const activeIlluminations = illuminations.filter((i) => i.is_active);

    // Build channels from active detectors + illumination combos
    const channels: Streams[] =
      activeDetectors.length > 0
        ? activeDetectors.map((det) => ({
            detector: det.name,
            mapping: det.current_colormap || "default",
            illuminations:
              activeIlluminations.length > 0
                ? activeIlluminations.map((ill) => {
                    return {
                      source: ill.kind ?? `slot_${ill.slot}`,
                      wavelength: ill.wavelength ?? 488,
                      intensity: ill.intensity / (ill.max_intensity || 100),
                    };
                  })
                : [makeDefaultIllumination()],
          }))
        : [makeDefaultStream()];

    const pos = makeDefaultPosition(
      stageState?.x ?? 0,
      stageState?.y ?? 0,
      stageState?.z ?? 0,
      channels,
    );

    return makeDefaultConfig([pos]);
  }, [cameraState, illuminationState, stageState]);

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

  const addTimepoint = () => {
    const defaults = buildDefaultsFromState();
    timepointsField.append(defaults.config.timepoints[0]);
    setSelectedTimepoint(timepointsField.fields.length);
    setSelectedPosition(0);
  };

  const removeTimepoint = (index: number) => {
    if (timepointsField.fields.length <= 1) return;
    timepointsField.remove(index);
    if (selectedTimepoint >= timepointsField.fields.length - 1) {
      setSelectedTimepoint(Math.max(0, timepointsField.fields.length - 2));
    }
    setSelectedPosition(0);
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

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" className="w-full h-14 justify-start">
          <Grid3X3 className="h-5 w-5 mr-3" />
          <div className="flex-1 text-left">
            <div className="font-medium">{t("acquisition.title")}</div>
            <div className="text-xs text-muted-foreground">
              {t("acquisition.summary")}
            </div>
          </div>
        </Button>
      </DialogTrigger>

      <DialogContent className="max-w-7xl h-[80vh] flex flex-col p-0 gap-0">
        <DialogHeader className="px-6 pt-6 pb-4">
          <DialogTitle className="flex items-center gap-2">
            <Grid3X3 className="h-5 w-5" />
            {t("acquisition.title")}
          </DialogTitle>
          <DialogDescription>{t("acquisition.description")}</DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form
            onSubmit={form.handleSubmit(onSubmit)}
            className="flex flex-col flex-1 min-h-0"
          >
            {/* Top bar: file settings + init-from-state */}
            <div className="px-6 pb-3 flex items-end gap-4">
              <FormField
                control={form.control}
                name="config.file_name"
                render={({ field }) => (
                  <FormItem className="flex-1">
                    <FormLabel className="text-xs">
                      {t("acquisition.fileName")}
                    </FormLabel>
                    <FormControl>
                      <Input {...field} placeholder="acquisition_001" />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="config.file_format"
                render={({ field }) => (
                  <FormItem className="w-28">
                    <FormLabel className="text-xs">
                      {t("acquisition.format")}
                    </FormLabel>
                    <FormControl>
                      <Input {...field} placeholder="tiff" />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="gap-1.5 shrink-0"
                onClick={handleInitFromState}
              >
                <RotateCcw className="h-3.5 w-3.5" />
                {t("acquisition.initFromState")}
              </Button>
            </div>

            <Separator />

            {/* ─── Main 3-pane layout ─── */}
            <div className="flex flex-1 min-h-0">
              {/* LEFT: Timepoints list */}
              <div className="w-48 border-r flex flex-col">
                <div className="px-3 py-2 flex items-center justify-between">
                  <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                    {t("acquisition.timepoints")}
                  </span>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6"
                    onClick={addTimepoint}
                  >
                    <Plus className="h-4 w-4" />
                  </Button>
                </div>
                <Separator />
                <ScrollArea className="flex-1">
                  <div className="p-1 space-y-0.5">
                    {timepointsField.fields.map((field, tpIdx) => {
                      const tpPositions =
                        form.watch(`config.timepoints.${tpIdx}.positions`) ??
                        [];
                      return (
                        <button
                          key={field.id}
                          type="button"
                          className={cn(
                            "group w-full text-left rounded-md px-3 py-2 text-sm transition-colors",
                            "hover:bg-accent",
                            tpIdx === safeTP && "bg-accent font-medium",
                          )}
                          onClick={() => {
                            setSelectedTimepoint(tpIdx);
                            setSelectedPosition(0);
                          }}
                        >
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <Clock className="h-3.5 w-3.5 text-muted-foreground" />
                              <span>T{tpIdx + 1}</span>
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
                          <div className="text-xs text-muted-foreground mt-0.5">
                            {t("acquisition.positionCount", {
                              count: tpPositions.length,
                            })}
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </ScrollArea>
              </div>

              {/* MIDDLE: Positions list */}
              <div className="w-44 border-r flex flex-col">
                <div className="px-3 py-2 flex items-center justify-between">
                  <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                    {t("acquisition.positionsLabel")}
                  </span>
                  <PositionAddButton
                    control={form.control}
                    timepointIndex={safeTP}
                    stageState={stageState}
                    defaultChannels={
                      buildDefaultsFromState().config.timepoints[0].positions[0]
                        .stacks[0].channels
                    }
                    onAdded={(idx) => setSelectedPosition(idx)}
                  />
                </div>
                <Separator />
                <ScrollArea className="flex-1">
                  <div className="p-1 space-y-0.5">
                    {positions.map((pos, posIdx) => (
                      <button
                        key={posIdx}
                        type="button"
                        className={cn(
                          "w-full text-left rounded-md px-3 py-2 text-sm transition-colors",
                          "hover:bg-accent",
                          posIdx === safePos && "bg-accent font-medium",
                        )}
                        onClick={() => setSelectedPosition(posIdx)}
                      >
                        <div className="flex items-center gap-2">
                          <MapPin className="h-3.5 w-3.5 text-muted-foreground" />
                          <span>P{posIdx + 1}</span>
                          <ChevronRight className="h-3 w-3 text-muted-foreground ml-auto" />
                        </div>
                        <div className="text-xs text-muted-foreground mt-0.5 font-mono">
                          ({pos.x}, {pos.y}, {pos.z})
                        </div>
                      </button>
                    ))}
                  </div>
                </ScrollArea>
              </div>

              {/* RIGHT: Position detail editor */}
              <ScrollArea className="flex-1">
                <div className="p-4 space-y-4">
                  {positions.length > 0 ? (
                    <PositionEditor
                      control={form.control}
                      timepointIndex={safeTP}
                      positionIndex={safePos}
                      onRemove={
                        positions.length > 1
                          ? () => {
                              const arr = form.getValues(
                                `config.timepoints.${safeTP}.positions`,
                              );
                              arr.splice(safePos, 1);
                              form.setValue(
                                `config.timepoints.${safeTP}.positions`,
                                arr,
                              );
                              setSelectedPosition(
                                Math.min(safePos, arr.length - 1),
                              );
                            }
                          : undefined
                      }
                    />
                  ) : (
                    <div className="flex items-center justify-center h-40 text-muted-foreground text-sm">
                      {t("acquisition.addPositionToStart")}
                    </div>
                  )}
                </div>
              </ScrollArea>
            </div>

            <Separator />

            {/* Footer */}
            <div className="px-6 py-4 space-y-3">
              {isLoading && progress !== null && (
                <div className="space-y-1">
                  <div className="flex items-center justify-between text-xs">
                    <span>{t("acquisition.progress")}</span>
                    <span>{Math.round(progress)}%</span>
                  </div>
                  <Progress value={progress} className="h-1.5" />
                </div>
              )}

              {task && (
                <div className="flex items-center justify-between">
                  <span className="text-xs text-muted-foreground">
                    {t("acquisition.status")}
                  </span>
                  <Badge
                    variant={
                      task.status === "completed" ? "default" : "secondary"
                    }
                  >
                    {t(`taskStatus.${task.status}`)}
                  </Badge>
                </div>
              )}

              <DialogFooter className="gap-2 sm:gap-2">
                {isLoading ? (
                  <Button
                    type="button"
                    variant="destructive"
                    onClick={handleCancel}
                  >
                    <Square className="h-4 w-4 mr-2" />
                    {t("common.cancel")}
                  </Button>
                ) : (
                  <Button type="submit" disabled={isLoading}>
                    <Play className="h-4 w-4 mr-2" />
                    {t("acquisition.start")}
                  </Button>
                )}
              </DialogFooter>
            </div>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Sub-component: Add position button
// ---------------------------------------------------------------------------

function PositionAddButton({
  control,
  timepointIndex,
  stageState,
  defaultChannels,
  onAdded,
}: {
  control: ReturnType<typeof useForm<FormValues>>["control"];
  timepointIndex: number;
  // The generated state type, not ReturnType<typeof useStageState>["data"] - the hook is
  // generic, so that indirection collapsed to {} and x/y/z were unreachable.
  stageState: StageState | null | undefined;
  defaultChannels: Streams[];
  onAdded: (index: number) => void;
}) {
  const { t } = useTranslation();
  const positionsField = useFieldArray({
    control,
    name: `config.timepoints.${timepointIndex}.positions`,
  });

  const addFromStage = () => {
    positionsField.append(
      makeDefaultPosition(
        stageState?.x ?? 0,
        stageState?.y ?? 0,
        stageState?.z ?? 0,
        defaultChannels,
      ),
    );
    onAdded(positionsField.fields.length);
  };

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      className="h-6 w-6"
      title={t("acquisition.addPositionFromStage")}
      onClick={addFromStage}
    >
      <Plus className="h-4 w-4" />
    </Button>
  );
}

// ---------------------------------------------------------------------------
// Sub-component: Position editor (right pane)
// ---------------------------------------------------------------------------

function PositionEditor({
  control,
  timepointIndex,
  positionIndex,
  onRemove,
}: {
  control: ReturnType<typeof useForm<FormValues>>["control"];
  timepointIndex: number;
  positionIndex: number;
  onRemove?: () => void;
}) {
  const { t } = useTranslation();
  const stacksField = useFieldArray({
    control,
    name: `config.timepoints.${timepointIndex}.positions.${positionIndex}.stacks`,
  });

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold flex items-center gap-2">
          <MapPin className="h-4 w-4" />
          {t("acquisition.position", { position: positionIndex + 1 })}
        </h3>
        {onRemove && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="text-destructive h-7 text-xs gap-1"
            onClick={onRemove}
          >
            <Trash2 className="h-3 w-3" />
            {t("acquisition.remove")}
          </Button>
        )}
      </div>

      {/* XYZ */}
      <div className="grid grid-cols-3 gap-3">
        {(["x", "y", "z"] as const).map((axis) => (
          <FormField
            key={axis}
            control={control}
            name={`config.timepoints.${timepointIndex}.positions.${positionIndex}.${axis}`}
            render={({ field }) => (
              <FormItem>
                <FormLabel className="text-xs uppercase">{axis} (µm)</FormLabel>
                <FormControl>
                  <Input
                    type="number"
                    step="any"
                    value={field.value}
                    onChange={(e) =>
                      field.onChange(parseFloat(e.target.value) || 0)
                    }
                    onBlur={field.onBlur}
                    name={field.name}
                    ref={field.ref}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        ))}
      </div>

      <Separator />

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
        className="w-full gap-1.5"
        onClick={() => stacksField.append(makeDefaultStack())}
      >
        <Plus className="h-3.5 w-3.5" />
        {t("acquisition.addStack")}
      </Button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-component: Stack editor
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
    <div className="rounded-lg border p-3 space-y-3">
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-semibold flex items-center gap-1.5">
          <Layers className="h-3.5 w-3.5" />
          {t("acquisition.stack", { stack: stackIndex + 1 })}
        </h4>
        {canRemove && (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            onClick={onRemove}
          >
            <Trash2 className="h-3 w-3 text-destructive" />
          </Button>
        )}
      </div>

      {/* Z params */}
      <div className="grid grid-cols-3 gap-2">
        <FormField
          control={control}
          name={`${stackBase}.z_offset`}
          render={({ field }) => (
            <FormItem>
              <FormLabel className="text-xs">
                Z {t("acquisition.offset")}
              </FormLabel>
              <FormControl>
                <Input
                  type="number"
                  step="any"
                  value={field.value}
                  onChange={(e) =>
                    field.onChange(parseFloat(e.target.value) || 0)
                  }
                  onBlur={field.onBlur}
                  name={field.name}
                  ref={field.ref}
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
              <FormLabel className="text-xs">
                Z {t("acquisition.step")}
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
                  onBlur={field.onBlur}
                  name={field.name}
                  ref={field.ref}
                />
              </FormControl>
            </FormItem>
          )}
        />
        {/* z_slices: number[] in schema, edit as comma-separated string */}
        <FormField
          control={control}
          name={`${stackBase}.z_slices`}
          render={({ field }) => (
            <FormItem>
              <FormLabel className="text-xs">
                Z {t("acquisition.slices")}
              </FormLabel>
              <FormControl>
                <Input
                  value={zSlicesToString(field.value ?? [])}
                  onChange={(e) =>
                    field.onChange(stringToZSlices(e.target.value))
                  }
                  onBlur={field.onBlur}
                  name={field.name}
                  ref={field.ref}
                  placeholder="-5, -3, 0, 3, 5"
                />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
      </div>

      {/* Channels */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-xs font-medium text-muted-foreground">
            {t("acquisition.channels")}
          </span>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-6 text-xs gap-1"
            onClick={() => channelsField.append(makeDefaultStream())}
          >
            <Plus className="h-3 w-3" />
            {t("acquisition.channels")}
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
// Sub-component: Channel (stream) editor
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

  return (
    <div className="rounded border p-2 space-y-2 bg-muted/30">
      <div className="flex gap-2 items-end">
        <FormField
          control={control}
          name={`${basePath}.detector`}
          render={({ field }) => (
            <FormItem className="flex-1">
              <FormLabel className="text-xs">
                {t("acquisition.detector")}
              </FormLabel>
              <FormControl>
                <Input {...field} placeholder="camera_1" />
              </FormControl>
            </FormItem>
          )}
        />
        <FormField
          control={control}
          name={`${basePath}.mapping`}
          render={({ field }) => (
            <FormItem className="flex-1">
              <FormLabel className="text-xs">
                {t("acquisition.mapping")}
              </FormLabel>
              <FormControl>
                <Input {...field} placeholder="GFP" />
              </FormControl>
            </FormItem>
          )}
        />
        {canRemove && (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-9 w-9 shrink-0"
            onClick={onRemove}
          >
            <Trash2 className="h-3.5 w-3.5 text-destructive" />
          </Button>
        )}
      </div>

      {/* Illuminations */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">
            Illuminations
          </span>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-5 text-[10px] px-1.5 gap-0.5"
            onClick={() => illuminationsField.append(makeDefaultIllumination())}
          >
            <Plus className="h-2.5 w-2.5" />
            Add
          </Button>
        </div>
        {illuminationsField.fields.map((illField, illIdx) => (
          <div key={illField.id} className="flex gap-1.5 items-end">
            <FormField
              control={control}
              name={`${basePath}.illuminations.${illIdx}.source`}
              render={({ field }) => (
                <FormItem className="flex-1">
                  <FormLabel className="text-[10px]">
                    {t("acquisition.source")}
                  </FormLabel>
                  <FormControl>
                    <Input {...field} className="h-7 text-xs" />
                  </FormControl>
                </FormItem>
              )}
            />
            <FormField
              control={control}
              name={`${basePath}.illuminations.${illIdx}.wavelength`}
              render={({ field }) => (
                <FormItem className="w-16">
                  <FormLabel className="text-[10px]">λ (nm)</FormLabel>
                  <FormControl>
                    <Input
                      type="number"
                      value={field.value}
                      onChange={(e) =>
                        field.onChange(parseFloat(e.target.value) || 0)
                      }
                      onBlur={field.onBlur}
                      name={field.name}
                      ref={field.ref}
                      className="h-7 text-xs"
                    />
                  </FormControl>
                </FormItem>
              )}
            />
            <FormField
              control={control}
              name={`${basePath}.illuminations.${illIdx}.intensity`}
              render={({ field }) => (
                <FormItem className="w-16">
                  <FormLabel className="text-[10px]">
                    {t("acquisition.intensity")}
                  </FormLabel>
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
                      onBlur={field.onBlur}
                      name={field.name}
                      ref={field.ref}
                      className="h-7 text-xs"
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
                className="h-7 w-7 shrink-0"
                onClick={() => illuminationsField.remove(illIdx)}
              >
                <Trash2 className="h-3 w-3 text-destructive" />
              </Button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
