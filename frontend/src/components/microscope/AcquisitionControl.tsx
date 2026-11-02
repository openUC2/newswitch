import { useAcquire } from "@/apps/default/hooks/actions";
import { useDetectorState } from "@/apps/default/hooks/states/DetectorState";
import { useSourceState } from "@/apps/default/hooks/states/SourceState";
import { useSwapState } from "@/apps/default/hooks/states/SwapState";
import { useTuneState } from "@/apps/default/hooks/states/TuneState";
import { usePauseTask } from "@/apps/default/hooks/usePauseTask";
import { useResumeTask } from "@/apps/default/hooks/useResumeTask";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { entriesOf, useStage } from "@/lib/microscope/values";
import {
  Crosshair,
  Pause,
  Play,
  Plus,
  RotateCcw,
  Square,
  X,
} from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { DetectorPicker } from "./DetectorPicker";

type Values = Record<string, number>;
type Channel = { name: string; detectors: string[]; set_to: Values };
type Place = { name: string; set_to: Values };

const Section = ({
  title,
  aside,
  children,
}: {
  title: string;
  aside?: React.ReactNode;
  children: React.ReactNode;
}) => (
  <div className="space-y-2">
    <div className="flex items-center justify-between gap-2">
      <span className="text-[10px] font-medium uppercase tracking-[0.2em] text-muted-foreground">
        {title}
      </span>
      {aside}
    </div>
    {children}
  </div>
);

const NumberField = ({
  label,
  unit,
  value,
  onChange,
  disabled,
  title,
}: {
  label: string;
  unit?: string;
  value: number;
  onChange: (value: number) => void;
  disabled?: boolean;
  title?: string;
}) => (
  <label className="flex min-w-0 flex-col gap-1" title={title}>
    <span className="truncate text-[11px] text-muted-foreground">
      {label}
      {unit ? ` (${unit})` : ""}
    </span>
    <Input
      type="number"
      className="h-8 text-xs"
      value={Number.isFinite(value) ? value : ""}
      disabled={disabled}
      onChange={(e) => onChange(parseFloat(e.target.value))}
    />
  </label>
);

/** What a plan is written in: every variable, in its description's name and with what it is now. */
const useVariables = () => {
  const { data: swaps } = useSwapState({ subscribe: true });
  const { data: tunes } = useTuneState({ subscribe: true });
  const { data: sources } = useSourceState({ subscribe: true });
  const { data: detectors } = useDetectorState({ subscribe: true });
  return {
    swaps: entriesOf(swaps?.swaps),
    tunes: tunes?.tunes ?? {},
    sources: Object.values(sources?.sources ?? {}),
    detectors: detectors?.detectors ?? [],
  };
};

const ChannelEditor = ({
  channel,
  onChange,
  onRemove,
}: {
  channel: Channel;
  onChange: (channel: Channel) => void;
  onRemove?: () => void;
}) => {
  const { t } = useTranslation();
  const { swaps, tunes, sources } = useVariables();
  const set = (name: string, value: number) =>
    onChange({ ...channel, set_to: { ...channel.set_to, [name]: value } });
  // Nothing wrong with a dark frame, if it is what is meant.
  const dark =
    sources.length > 0 &&
    sources.every(
      (source) =>
        source.power_variable && !channel.set_to[source.power_variable],
    );
  // A detector's own tunes, but for what is no setting of a single image.
  const detectorTunes = channel.detectors.flatMap((detector) =>
    Object.values(tunes[detector] ?? {}).filter(
      (tune) => !tune.name.endsWith(".frame_rate"),
    ),
  );

  return (
    <div className="space-y-3 rounded-lg border p-3">
      <div className="flex items-center gap-2">
        <Input
          className="h-8 text-xs"
          placeholder={t("acquisition.name")}
          value={channel.name}
          onChange={(e) => onChange({ ...channel, name: e.target.value })}
        />
        {onRemove && (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="size-8"
            onClick={onRemove}
          >
            <X className="size-3.5" />
          </Button>
        )}
      </div>
      {dark && (
        <div className="rounded-md border border-warning/30 bg-warning/10 px-2 py-1.5 text-[11px] text-warning">
          {t("acquisition.dark")}
        </div>
      )}
      <DetectorPicker
        value={channel.detectors}
        onChange={(detectors) => onChange({ ...channel, detectors })}
      />
      <div className="grid grid-cols-2 gap-2">
        {sources
          .filter((source) => source.power_variable)
          .map((source) => (
            <NumberField
              key={source.name}
              label={`${source.name} power`}
              unit="mW"
              title={t("acquisition.sourceRange", { max: source.max_power })}
              value={channel.set_to[source.power_variable as string] ?? 0}
              onChange={(value) => set(source.power_variable as string, value)}
            />
          ))}
        {detectorTunes.map((tune) => (
          <NumberField
            key={tune.name}
            label={tune.name}
            unit={tune.unit}
            value={channel.set_to[tune.name] ?? tune.value}
            onChange={(value) => set(tune.name, value)}
          />
        ))}
      </div>
      {swaps.map((swap) => (
        <div key={swap.name} className="space-y-1">
          <div className="text-[11px] text-muted-foreground">{swap.name}</div>
          <div className="flex flex-wrap gap-1">
            {swap.options.map((option) => (
              <Button
                key={option.slot}
                type="button"
                size="sm"
                className="h-7 px-2 text-xs"
                variant={
                  (channel.set_to[swap.name] ?? swap.value) === option.slot
                    ? "default"
                    : "outline"
                }
                onClick={() => set(swap.name, option.slot)}
              >
                {option.label}
              </Button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
};

/** Where the detailed plan starts: what the planner chose, its channels, depth and time. */
export type DetailedStart = {
  channels?: Channel[];
  planes?: number;
  step?: number;
  times?: number;
  every?: number;
};

/** An acquisition, as a plan over what this microscope has: every channel, on every plane, at every
 * position, every time, every setting of it. It starts from `initial`, or else from what is set
 * now, and asks only for what is here. */
export function DetailedPlan({ initial }: { initial?: DetailedStart }) {
  const { t } = useTranslation();
  const { swaps, tunes, sources, detectors } = useVariables();
  const stage = useStage();
  const { assign: start, isLoading, task, progress, cancel } = useAcquire();
  const pause = usePauseTask();
  const resume = useResumeTask();

  const moving = useMemo(
    () => [...stage.x, ...stage.y, ...stage.focus],
    [stage.x, stage.y, stage.focus],
  );
  const here = useCallback((): Place => {
    const set_to: Values = {};
    for (const move of moving) set_to[move.name] = move.value;
    return { name: "", set_to };
  }, [moving]);
  const fromNow = useCallback((): Channel => {
    const set_to: Values = {};
    for (const source of sources) {
      if (source.power_variable) set_to[source.power_variable] = source.power;
    }
    for (const swap of swaps) set_to[swap.name] = swap.value;
    const picked = detectors.filter((d) => d.is_active).map((d) => d.name);
    for (const detector of picked) {
      for (const tune of Object.values(tunes[detector] ?? {})) {
        if (!tune.name.endsWith(".frame_rate")) set_to[tune.name] = tune.value;
      }
    }
    return { name: "", detectors: picked, set_to };
  }, [sources, swaps, detectors, tunes]);

  const [name, setName] = useState("acquisition");
  // What it starts from is what is set now, until it is edited.
  const [editedChannels, setChannels] = useState<Channel[] | null>(
    initial?.channels ?? null,
  );
  const [editedPlaces, setPlaces] = useState<Place[] | null>(null);
  const known = detectors.length > 0;
  const channels = editedChannels ?? (known ? [fromNow()] : null);
  const places = editedPlaces ?? (known ? [here()] : null);
  const [planes, setPlanes] = useState(initial?.planes ?? 1);
  const [step, setStep] = useState(initial?.step ?? 1);
  const [focus, setFocus] = useState<string | null>(null);
  const [times, setTimes] = useState(initial?.times ?? 1);
  const [every, setEvery] = useState(initial?.every ?? 0);
  const [refocus, setRefocus] = useState(false);

  // A detector whose wire steps what focuses says how far apart the planes are.
  const drivenStep = detectors
    .filter((d) => channels?.some((c) => c.detectors.includes(d.name)))
    .flatMap((d) => d.axes)
    .find((axis) => axis.name === "z")?.step;
  const usedStep = drivenStep ?? step;
  const ambiguous = stage.focus.length > 1 && planes > 1 && focus === null;
  const offsets =
    planes > 1
      ? Array.from(
          { length: planes },
          (_, i) => (i - (planes - 1) / 2) * usedStep,
        )
      : [];

  const submit = () => {
    if (!channels || !places) return;
    start(
      {
        plan: {
          name,
          channels,
          positions: places,
          stack: { offsets, variable: focus },
          times,
          every_s: every,
          order: "SEQUENTIAL",
          m_hooks: [],
          t_hooks: [],
          p_hooks: refocus
            ? [
                {
                  __identifier: "@newswitch/software_autofocus_hook",
                  steps: 11,
                },
              ]
            : [],
          z_hooks: [],
        },
      },
      { notify: true },
    );
  };

  return (
    <div className="w-full space-y-4">
      <Section
        title={t("acquisition.channels")}
        aside={
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-7 px-2 text-xs"
            onClick={() => setChannels([...(channels ?? []), fromNow()])}
          >
            <Plus className="mr-1 size-3" />
            {t("acquisition.add")}
          </Button>
        }
      >
        {channels?.map((channel, index) => (
          <ChannelEditor
            key={index}
            channel={channel}
            onChange={(next) =>
              setChannels(channels.map((c, i) => (i === index ? next : c)))
            }
            onRemove={
              channels.length > 1
                ? () => setChannels(channels.filter((_, i) => i !== index))
                : undefined
            }
          />
        ))}
      </Section>

      <Separator />

      <Section
        title={t("acquisition.positions")}
        aside={
          <div className="flex gap-1">
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="h-7 px-2 text-xs"
              onClick={() => setPlaces([...(places ?? []), here()])}
            >
              <Crosshair className="mr-1 size-3" />
              {t("acquisition.addHere")}
            </Button>
          </div>
        }
      >
        <div className="text-[11px] text-muted-foreground">
          {t("acquisition.positionsAreDatasets")}
        </div>
        {stage.focus.length === 1 && (
          <label className="flex items-center gap-2 text-xs">
            <Switch checked={refocus} onCheckedChange={setRefocus} />
            {t("acquisition.refocus")}
          </label>
        )}
        {places?.map((place, index) => (
          <div key={index} className="flex items-end gap-2">
            <div className="grid min-w-0 flex-1 grid-cols-3 gap-2">
              {moving.map((move) => (
                <NumberField
                  key={move.name}
                  label={move.name}
                  unit={move.unit}
                  value={place.set_to[move.name] ?? move.value}
                  onChange={(value) =>
                    setPlaces(
                      places.map((p, i) =>
                        i === index
                          ? {
                              ...p,
                              set_to: { ...p.set_to, [move.name]: value },
                            }
                          : p,
                      ),
                    )
                  }
                />
              ))}
            </div>
            {places.length > 1 && (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="size-8"
                onClick={() => setPlaces(places.filter((_, i) => i !== index))}
              >
                <X className="size-3.5" />
              </Button>
            )}
          </div>
        ))}
      </Section>

      <Separator />

      <Section title={t("acquisition.stack")}>
        <div className="grid grid-cols-2 gap-2">
          <NumberField
            label={t("acquisition.planes")}
            value={planes}
            onChange={(value) => setPlanes(Math.max(1, Math.round(value) || 1))}
          />
          <NumberField
            label={t("acquisition.step")}
            unit={stage.focus[0]?.unit}
            value={usedStep}
            disabled={drivenStep != null}
            title={drivenStep != null ? t("acquisition.stepOfWire") : undefined}
            onChange={setStep}
          />
        </div>
        {stage.focus.length > 1 && (
          <div className="flex flex-wrap items-center gap-1">
            <span className="text-[11px] text-muted-foreground">
              {t("acquisition.sweepWith")}
            </span>
            {stage.focus.map((move) => (
              <Button
                key={move.name}
                type="button"
                size="sm"
                className="h-7 px-2 text-xs"
                variant={focus === move.name ? "default" : "outline"}
                onClick={() => setFocus(move.name)}
              >
                {move.name}
              </Button>
            ))}
          </div>
        )}
      </Section>

      <Separator />

      <Section title={t("acquisition.times")}>
        <div className="grid grid-cols-2 gap-2">
          <NumberField
            label={t("acquisition.howOften")}
            value={times}
            onChange={(value) => setTimes(Math.max(1, Math.round(value) || 1))}
          />
          <NumberField
            label={t("acquisition.every")}
            unit="s"
            value={every}
            onChange={(value) => setEvery(Math.max(0, value || 0))}
          />
        </div>
      </Section>

      <Separator />

      <div className="flex items-end gap-2">
        <label className="flex min-w-0 flex-1 flex-col gap-1">
          <span className="text-[11px] text-muted-foreground">
            {t("acquisition.name")}
          </span>
          <Input
            className="h-8 text-xs"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-8 px-2 text-xs"
          title={t("acquisition.fromNow")}
          onClick={() => {
            setChannels(null);
            setPlaces(null);
          }}
        >
          <RotateCcw className="size-3.5" />
        </Button>
      </div>

      {(isLoading || task) && (
        <div className="space-y-2 rounded-lg bg-muted/50 p-3">
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
          {progress !== null && <Progress value={progress} className="h-1.5" />}
        </div>
      )}

      <div className="flex gap-2">
        {isLoading ? (
          <>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-9 flex-1"
              onClick={() => task?.id && cancel()}
            >
              <Square className="mr-1.5 size-3.5" />
              {t("common.cancel")}
            </Button>
            {task?.status === "paused" ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-9 flex-1 animate-pulse"
                onClick={() => task?.id && resume(task.id)}
              >
                <Play className="mr-1.5 size-3.5" />
                {t("microscope.resume")}
              </Button>
            ) : (
              <Button
                type="button"
                variant="destructive"
                size="sm"
                className="h-9 flex-1"
                onClick={() => task?.id && pause(task.id)}
              >
                <Pause className="mr-1.5 size-3.5" />
                {t("microscope.pause")}
              </Button>
            )}
          </>
        ) : (
          <Button
            type="button"
            size="sm"
            className="h-9 flex-1"
            disabled={ambiguous || !channels?.length}
            title={ambiguous ? t("acquisition.whichToSweep") : undefined}
            onClick={submit}
          >
            <Play className="mr-1.5 size-3.5" />
            {t("acquisition.start")}
          </Button>
        )}
      </div>
    </div>
  );
}
