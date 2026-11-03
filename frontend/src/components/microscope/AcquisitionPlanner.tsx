import { useAcquire } from "@/apps/default/hooks/actions";
import { useDetectorState } from "@/apps/default/hooks/states/DetectorState";
import { useMoveState } from "@/apps/default/hooks/states/MoveState";
import {
  useOpticsState,
  type OpticalChannel,
} from "@/apps/default/hooks/states/OpticsState";
import { useSourceState } from "@/apps/default/hooks/states/SourceState";
import { useSpaceState } from "@/apps/default/hooks/states/SpaceState";
import { useSwapState } from "@/apps/default/hooks/states/SwapState";
import { useTuneState } from "@/apps/default/hooks/states/TuneState";
import { usePauseTask } from "@/apps/default/hooks/usePauseTask";
import { useResumeTask } from "@/apps/default/hooks/useResumeTask";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import {
  buildPlan,
  estimate,
  formatBytes,
  formatDuration,
  isChannel,
  PlanProblem,
  swapsKey,
  stackOffsets,
  type ChannelChoice,
  type Choices,
  type Depth,
  type PlanContext,
  type Time,
  type Where,
} from "@/lib/microscope/plan";
import {
  deliversImages,
  toMatrix4,
  useLookingAt,
} from "@/lib/microscope/space";
import { useSceneSample } from "@/lib/microscope/sampleContext";
import { entriesOf, useStage } from "@/lib/microscope/values";
import { cn } from "@/lib/utils";
import {
  Crosshair,
  Pause,
  Play,
  SlidersHorizontal,
  Square,
  Undo2,
  X,
} from "lucide-react";
import { useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { Vector3 } from "three";
import { useTranslation } from "react-i18next";
import { DetailedPlan, type DetailedStart } from "./AcquisitionControl";

const tint = (color?: string | null) =>
  ({
    "--c": color ? `var(--spectrum-${color})` : "var(--muted-foreground)",
  }) as CSSProperties;

const round = (value: number, digits = 2) =>
  Number.isFinite(value) ? Number(value.toFixed(digits)) : 0;

/** One step of the plan: a number, a title, and what to choose. */
const Step = ({
  index,
  title,
  aside,
  children,
}: {
  index: number;
  title: string;
  aside?: ReactNode;
  children: ReactNode;
}) => (
  <section className="space-y-3 rounded-2xl border border-border/60 bg-card/70 p-4 shadow-sm">
    <div className="flex items-center gap-2.5">
      <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-primary/15 text-xs font-semibold text-primary">
        {index}
      </span>
      <span className="text-sm font-semibold tracking-tight">{title}</span>
      <div className="ml-auto">{aside}</div>
    </div>
    {children}
  </section>
);

/** A choice between a few kinds, each with a word of what it is. */
const Segmented = <T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}) => (
  <div className="inline-flex rounded-lg border border-border/60 bg-muted/40 p-0.5">
    {options.map((option) => (
      <button
        key={option.value}
        type="button"
        aria-pressed={option.value === value}
        onClick={() => onChange(option.value)}
        className={cn(
          "rounded-md px-3 py-1 text-xs font-medium transition-colors",
          option.value === value
            ? "bg-background text-foreground shadow-sm"
            : "text-muted-foreground hover:text-foreground",
        )}
      >
        {option.label}
      </button>
    ))}
  </div>
);

/** A number with a unit, small. */
const Amount = ({
  label,
  unit,
  value,
  onChange,
  min = 0,
  step,
  disabled,
  hint,
}: {
  label: string;
  unit?: string;
  value: number;
  onChange: (value: number) => void;
  min?: number;
  step?: number;
  disabled?: boolean;
  hint?: string;
}) => (
  <label className="flex min-w-0 flex-col gap-1">
    <span className="truncate text-[11px] text-muted-foreground">{label}</span>
    <div className="flex items-center gap-1.5">
      <Input
        type="number"
        className="h-8 text-xs tabular-nums"
        value={Number.isFinite(value) ? value : ""}
        min={min}
        step={step}
        disabled={disabled}
        onChange={(e) => {
          const next = parseFloat(e.target.value);
          if (Number.isFinite(next)) onChange(Math.max(min, next));
        }}
      />
      {unit && <span className="text-xs text-muted-foreground">{unit}</span>}
    </div>
    {hint && <span className="text-[10px] text-muted-foreground">{hint}</span>}
  </label>
);

/** A slider with its value beside it. */
const Level = ({
  label,
  value,
  unit,
  min,
  max,
  step,
  onChange,
}: {
  label: string;
  value: number;
  unit: string;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
}) => (
  <div className="grid grid-cols-[4.5rem_1fr_4.5rem] items-center gap-2">
    <span className="text-[11px] text-muted-foreground">{label}</span>
    <Slider
      value={[value]}
      min={min}
      max={max}
      step={step}
      onValueChange={([next]) => onChange(next)}
    />
    <span className="text-right text-xs tabular-nums">
      {round(value, value < 1 ? 3 : 1)} {unit}
    </span>
  </div>
);

/** A plate's wells as it lies: click one, or a row's letter or a column's number for all of it. */
const PlateMap = ({
  wells,
  picked,
  onChange,
}: {
  wells: string[];
  picked: string[];
  onChange: (wells: string[]) => void;
}) => {
  const parse = (well: string) => {
    const short = well.split(":").at(-1) ?? well;
    return {
      row: short.replace(/\d+$/, ""),
      column: Number(short.match(/\d+$/)?.[0]),
    };
  };
  const rows = [...new Set(wells.map((w) => parse(w).row))].sort();
  const columns = [...new Set(wells.map((w) => parse(w).column))].sort(
    (a, b) => a - b,
  );
  const at = new Map(
    wells.map((w) => [`${parse(w).row}${parse(w).column}`, w]),
  );
  const chosen = new Set(picked);
  const toggleAll = (group: string[]) => {
    const all = group.every((w) => chosen.has(w));
    const next = new Set(chosen);
    group.forEach((w) => (all ? next.delete(w) : next.add(w)));
    onChange(wells.filter((w) => next.has(w)));
  };
  return (
    <div
      className="grid gap-[3px]"
      style={{
        gridTemplateColumns: `1rem repeat(${columns.length}, minmax(0, 1fr))`,
      }}
    >
      <span />
      {columns.map((column) => (
        <button
          key={column}
          type="button"
          className="text-[9px] text-muted-foreground hover:text-foreground"
          onClick={() =>
            toggleAll(wells.filter((w) => parse(w).column === column))
          }
        >
          {column}
        </button>
      ))}
      {rows.map((row) => (
        <div key={row} className="contents">
          <button
            type="button"
            className="text-[9px] text-muted-foreground hover:text-foreground"
            onClick={() => toggleAll(wells.filter((w) => parse(w).row === row))}
          >
            {row}
          </button>
          {columns.map((column) => {
            const well = at.get(`${row}${column}`);
            if (!well) return <span key={column} />;
            const on = chosen.has(well);
            return (
              <button
                key={column}
                type="button"
                title={`${row}${column}`}
                aria-pressed={on}
                onClick={() => toggleAll([well])}
                className={cn(
                  "aspect-square rounded-full border transition-colors",
                  on
                    ? "border-primary bg-primary"
                    : "border-border bg-muted/40 hover:bg-muted",
                )}
              />
            );
          })}
        </div>
      ))}
    </div>
  );
};

/** The grid of tiles, drawn to scale: each a field of view, overlapping by what is chosen. */
const GridPreview = ({
  rows,
  columns,
  overlap,
  field,
}: {
  rows: number;
  columns: number;
  overlap: number;
  field: { width: number; height: number };
}) => {
  const share = 1 - overlap;
  const width = field.width * (1 + (columns - 1) * share);
  const height = field.height * (1 + (rows - 1) * share);
  const scale = 120 / Math.max(width, height);
  return (
    <svg
      width={width * scale + 4}
      height={height * scale + 4}
      className="shrink-0"
      aria-hidden
    >
      {Array.from({ length: rows }).flatMap((_, row) =>
        Array.from({ length: columns }).map((_, column) => (
          <rect
            key={`${row}-${column}`}
            x={2 + column * field.width * share * scale}
            y={2 + row * field.height * share * scale}
            width={field.width * scale}
            height={field.height * scale}
            className="fill-primary/15 stroke-primary"
            strokeWidth={1}
          />
        )),
      )}
    </svg>
  );
};

const length = (um: number) =>
  um >= 1000 ? `${round(um / 1000, 2)} mm` : `${Math.round(um)} µm`;

/** The microscope as it is now, in the terms the planner chooses in. */
const useMicroscope = () => {
  const { data: optics } = useOpticsState({ subscribe: true });
  const { data: sources } = useSourceState({ subscribe: true });
  const { data: tunes } = useTuneState({ subscribe: true });
  const { data: swaps } = useSwapState({ subscribe: true });
  const { data: detectorState } = useDetectorState({ subscribe: true });
  const { data: space } = useSpaceState({ subscribe: true });
  const { data: moves } = useMoveState({ subscribe: true });
  const looking = useLookingAt();
  const sceneSample = useSceneSample();
  const stage = useStage();

  const sourceOf = (name: string) =>
    Object.values(sources?.sources ?? {}).find((s) => s.name === name);
  const exposureOf = (detector: string) =>
    Object.values(tunes?.tunes?.[detector] ?? {}).find(
      (tune) => tune.name === `${detector}.exposure`,
    );
  const sampleOf = (detector: string) =>
    space?.detectors?.[detector]?.sample ?? space?.points?.[detector]?.sample;
  /** The sample point where `sample`'s stage has it under the view: its moves through its mount. */
  const stageLookingAt = (sample: string) => {
    const along = (axis: string) =>
      Object.values(moves?.moves?.[sample] ?? {})
        .filter((move) => move.along === axis && move.does.includes("position"))
        .reduce((total, move) => total + move.value, 0);
    const mount = space?.samples?.[sample]?.mount;
    if (!mount) return undefined;
    return new Vector3(along("x"), along("y"), 0).applyMatrix4(
      toMatrix4(mount),
    );
  };
  return {
    optics,
    channels: optics?.channels ?? [],
    detectors: detectorState?.detectors ?? [],
    pointDetectors: (detectorState?.detectors ?? []).filter(
      (d) => !deliversImages(d),
    ),
    swaps: Object.fromEntries(
      entriesOf(swaps?.swaps).map((s) => [s.name, s.value]),
    ),
    samples: Object.values(space?.samples ?? {}),
    sampleCount: Object.keys(space?.samples ?? {}).length,
    moves: entriesOf(moves?.moves),
    looking,
    lookingSample: sceneSample,
    stageLookingAt,
    focusMoves: stage.focus.map((move) => move.name),
    sourceOf,
    exposureOf,
    sampleOf,
  };
};

/** The swaps a channel takes, by variable. */
const swapsOf = (channel: OpticalChannel): Record<string, number> =>
  Object.fromEntries((channel.swaps ?? []).map((s) => [s.variable, s.slot]));

/** A channel's name in the plan: its source, and what its swaps put in place. */
const nameOf = (channel: OpticalChannel): string =>
  [channel.source, ...(channel.swaps ?? []).map((s) => s.label)].join(" · ");

type Microscope = ReturnType<typeof useMicroscope>;

/** A channel the optics found, chosen: at the brightness it has now, or its preset. */
const choiceOf = (m: Microscope, channel: OpticalChannel): ChannelChoice => {
  const found = m.sourceOf(channel.source);
  const power =
    found?.on && found.power > 0 ? found.power : found?.lit_power || 0;
  return {
    source: channel.source,
    detector: channel.detector,
    power: power || (found?.max_power ?? 1) / 5,
    exposure: m.exposureOf(channel.detector)?.value,
    swaps: swapsOf(channel),
    name: nameOf(channel),
  };
};

/** What it would image, from what is set now: the lights that are on, on the cameras that are,
 * under the swaps as they are. */
const startingChannels = (m: Microscope): ChannelChoice[] => {
  const lit = m.channels.filter(
    (c) =>
      m.sourceOf(c.source)?.on &&
      m.detectors.find((d) => d.name === c.detector)?.is_active &&
      (c.swaps ?? []).every((s) => m.swaps[s.variable] === s.slot),
  );
  const first = m.channels.slice(0, 1);
  return (lit.length > 0 ? lit : first).map((c) => choiceOf(m, c));
};

const ChannelCard = ({
  m,
  channel,
  choice,
  onToggle,
  onChange,
}: {
  m: Microscope;
  channel: OpticalChannel;
  choice?: ChannelChoice;
  onToggle: () => void;
  onChange: (choice: ChannelChoice) => void;
}) => {
  const { t } = useTranslation();
  const { source, detector } = channel;
  const band = channel.band_nm;
  const found = m.sourceOf(source);
  const exposure = m.exposureOf(detector);
  const sample = m.sampleCount > 1 ? channel.sample : undefined;
  return (
    <div
      style={tint(found?.color)}
      className={cn(
        "rounded-xl border p-3 transition-colors",
        choice
          ? "border-[var(--c)] bg-[color-mix(in_oklab,var(--c)_10%,transparent)]"
          : "border-border/60 bg-muted/20 opacity-80 hover:opacity-100",
      )}
    >
      <button
        type="button"
        aria-pressed={!!choice}
        onClick={onToggle}
        className="flex w-full items-center gap-2.5 text-left"
      >
        <span
          className={cn(
            "size-3 shrink-0 rounded-full border-2 border-[var(--c)]",
            choice && "bg-[var(--c)]",
          )}
        />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium">
            {source} <span className="text-muted-foreground">→</span> {detector}
          </span>
          <span className="block truncate text-[11px] text-muted-foreground">
            {band ? `${Math.round(band)} nm` : ""}
            {sample ? ` · ${sample}` : ""}
          </span>
        </span>
      </button>
      {(channel.swaps ?? []).length > 0 && (
        <div
          className="mt-2 flex flex-wrap gap-1"
          title={t("acquisition.planner.swapsHint")}
        >
          {(channel.swaps ?? []).map((swap) => (
            <span
              key={swap.variable}
              className="rounded-full border border-border/60 bg-background/60 px-2 py-0.5 text-[10px] text-muted-foreground"
            >
              <span className="font-mono">{swap.variable.split(".")[0]}</span> ·{" "}
              {swap.label}
            </span>
          ))}
        </div>
      )}
      {choice && (
        <div className="mt-3 space-y-2">
          {found?.power_variable && (
            <Level
              label={t("acquisition.planner.brightness")}
              value={choice.power}
              unit="mW"
              min={0}
              max={found.max_power}
              step={found.max_power / 200}
              onChange={(power) => onChange({ ...choice, power })}
            />
          )}
          {exposure && choice.exposure !== undefined && (
            <Level
              label={t("acquisition.planner.exposure")}
              value={choice.exposure}
              unit={exposure.unit}
              min={exposure.minimum ?? 1}
              max={Math.min(exposure.maximum ?? 1000, 2000)}
              step={exposure.step ?? 1}
              onChange={(value) => onChange({ ...choice, exposure: value })}
            />
          )}
        </div>
      )}
    </div>
  );
};

/** An acquisition in four choices: what to image, where, how deep, how often; with what that comes
 * to, and every detail one click away (Fine-tune). The plan itself is `buildPlan`'s. */
export function AcquisitionControl() {
  const { t } = useTranslation();
  const m = useMicroscope();
  const { assign: start, isLoading, task, progress, cancel } = useAcquire();
  const pause = usePauseTask();
  const resume = useResumeTask();

  const [name, setName] = useState("");
  const [picked, setPicked] = useState<ChannelChoice[] | null>(null);
  const channels = picked ?? startingChannels(m);
  const [alsoRecord, setAlsoRecord] = useState<string[]>([]);
  const [where, setWhere] = useState<Where>({ kind: "here" });
  const [depth, setDepth] = useState<Depth>({ kind: "plane" });
  const [time, setTime] = useState<Time>({ kind: "once" });
  const [refocus, setRefocus] = useState(false);
  const [detailed, setDetailed] = useState<DetailedStart | null>(null);

  const chosen = channels.map((c) => c.detector);
  const found = channels
    .map((c) =>
      m.channels.find((x) => isChannel(c, x.source, x.detector, swapsOf(x))),
    )
    .filter((c) => c !== undefined);
  // What every channel chosen sees, under its own swaps: a switch may be set otherwise now.
  const field =
    found.length > 0
      ? {
          width: Math.min(...found.map((c) => c.field_width_um ?? 0)),
          height: Math.min(...found.map((c) => c.field_height_um ?? 0)),
        }
      : undefined;
  const fields = chosen
    .map((d) => m.optics?.detectors?.[d])
    .filter((d) => d !== undefined);
  const depthOfField = Math.min(
    ...fields.map((d) => d.depth_of_field_um).filter((v) => v > 0),
  );
  const drivenStep = m.detectors
    .filter((d) => chosen.includes(d.name))
    .flatMap((d) => d.axes)
    .find((axis) => axis.name === "z")?.step;
  const samples = [
    ...new Set(
      [...found.map((c) => c.sample), ...alsoRecord.map(m.sampleOf)].filter(
        (s) => s !== undefined && s !== "",
      ),
    ),
  ] as string[];
  // Where a grid goes: around where the view is, if it is of a sample imaged; else where that
  // sample's stage has it, which no camera may see now.
  const looking =
    m.looking &&
    (m.lookingSample === undefined || samples.includes(m.lookingSample))
      ? m.looking
      : samples.length > 0
        ? m.stageLookingAt(samples[0])
        : m.looking;
  const plates = m.samples.filter((s) => (s.shape?.wells.length ?? 0) > 0);

  const context: PlanContext = {
    swaps: m.swaps,
    powerVariables: Object.fromEntries(
      m.channels
        .map((c) => [c.source, m.sourceOf(c.source)?.power_variable])
        .filter(([, variable]) => !!variable),
    ),
    exposureVariables: Object.fromEntries(
      m.detectors
        .map((d) => [d.name, m.exposureOf(d.name)?.name])
        .filter(([, variable]) => !!variable),
    ),
    looking: looking ? { x: looking.x, y: looking.y } : undefined,
    field,
    drivenStep: drivenStep ?? undefined,
    samples,
  };
  const choices: Choices = {
    name,
    channels,
    alsoRecord,
    where,
    depth,
    time,
    refocus,
  };
  const built = useMemo(() => {
    try {
      return { plan: buildPlan(choices, context) };
    } catch (error) {
      if (error instanceof PlanProblem) return { problem: error.message };
      throw error;
    }
    // The plan is a function of what is chosen and what the microscope is now.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(choices), JSON.stringify(context)]);
  const cost = built.plan
    ? estimate(built.plan, m.detectors, (detector, channel) => {
        const variable = context.exposureVariables[detector];
        return (
          (variable && channel.set_to[variable]) ||
          m.exposureOf(detector)?.value ||
          0
        );
      })
    : undefined;

  const toggle = (channel: OpticalChannel) => {
    const on = channels.find((c) =>
      isChannel(c, channel.source, channel.detector, swapsOf(channel)),
    );
    if (on) {
      setPicked(channels.filter((c) => c !== on));
      return;
    }
    setPicked([...channels, choiceOf(m, channel)]);
  };
  const here = () => {
    const set_to: Record<string, number> = {};
    for (const move of m.moves) {
      if (move.does.includes("position") || move.does.includes("blur")) {
        set_to[move.name] = move.value;
      }
    }
    return set_to;
  };

  if (detailed) {
    return (
      <div className="w-full space-y-3">
        <div className="flex items-center justify-between gap-2">
          <span className="text-[11px] text-muted-foreground">
            {t("acquisition.planner.fineTuneHint")}
          </span>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-7 shrink-0 text-xs"
            onClick={() => setDetailed(null)}
          >
            <Undo2 className="mr-1 size-3.5" />
            {t("acquisition.planner.simple")}
          </Button>
        </div>
        <DetailedPlan initial={detailed} />
      </div>
    );
  }

  const running = isLoading || !!task;
  const stack = depth.kind === "stack" ? depth : undefined;
  const lapse = time.kind === "lapse" ? time : undefined;

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-3">
      <div className="flex items-center gap-3 px-1">
        <span className="text-lg font-semibold tracking-tight">
          {t("acquisition.planner.title")}
        </span>
        <Input
          className="h-8 max-w-56 text-sm"
          placeholder={t("acquisition.planner.namePlaceholder")}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="ml-auto h-8 text-xs"
          title={t("acquisition.planner.fineTuneHint")}
          onClick={() =>
            setDetailed({
              channels: built.plan?.channels.map((c) => ({
                name: c.name ?? "",
                detectors: [...c.detectors],
                set_to: { ...c.set_to },
              })),
              planes: Math.max(1, built.plan?.stack.offsets.length ?? 1),
              step:
                stack !== undefined ? (drivenStep ?? stack.step) : undefined,
              times: built.plan?.times,
              every: built.plan?.every_s,
            })
          }
        >
          <SlidersHorizontal className="mr-1 size-3.5" />
          {t("acquisition.planner.fineTune")}
        </Button>
      </div>

      <Step index={1} title={t("acquisition.planner.what")}>
        {m.channels.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            {t("acquisition.planner.noChannels")}
          </p>
        ) : (
          <>
            <p className="text-[11px] text-muted-foreground">
              {t("acquisition.planner.whatHint")}
            </p>
            <div className="grid gap-2 sm:grid-cols-2">
              {m.channels.map((c) => {
                const choice = channels.find((x) =>
                  isChannel(x, c.source, c.detector, swapsOf(c)),
                );
                return (
                  <ChannelCard
                    key={`${c.source}-${c.detector}-${swapsKey(swapsOf(c))}`}
                    m={m}
                    channel={c}
                    choice={choice}
                    onToggle={() => toggle(c)}
                    onChange={(next) =>
                      setPicked(channels.map((x) => (x === choice ? next : x)))
                    }
                  />
                );
              })}
            </div>
          </>
        )}
        {m.pointDetectors.length > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[11px] text-muted-foreground">
              {t("acquisition.planner.alsoRecord")}
            </span>
            {m.pointDetectors.map((d) => {
              const on = alsoRecord.includes(d.name);
              return (
                <Button
                  key={d.name}
                  type="button"
                  size="sm"
                  variant={on ? "default" : "outline"}
                  className="h-7 px-2.5 text-xs"
                  aria-pressed={on}
                  onClick={() =>
                    setAlsoRecord(
                      on
                        ? alsoRecord.filter((n) => n !== d.name)
                        : [...alsoRecord, d.name],
                    )
                  }
                >
                  {d.name} · {d.quantity}
                </Button>
              );
            })}
          </div>
        )}
      </Step>

      <Step
        index={2}
        title={t("acquisition.planner.where")}
        aside={
          <Segmented
            value={where.kind}
            options={[
              { value: "here", label: t("acquisition.planner.here") },
              { value: "grid", label: t("acquisition.planner.grid") },
              ...(plates.length > 0
                ? [
                    {
                      value: "wells" as const,
                      label: t("acquisition.planner.wells"),
                    },
                  ]
                : []),
              { value: "spots", label: t("acquisition.planner.spots") },
            ]}
            onChange={(kind) =>
              setWhere(
                kind === "grid"
                  ? { kind, rows: 3, columns: 3, overlap: 0.1 }
                  : kind === "wells"
                    ? { kind, wells: [] }
                    : kind === "spots"
                      ? { kind, spots: [{ name: "P1", set_to: here() }] }
                      : { kind: "here" },
              )
            }
          />
        }
      >
        {where.kind === "here" && (
          <p className="text-[11px] text-muted-foreground">
            {t("acquisition.planner.hereHint")}
          </p>
        )}
        {where.kind === "grid" && (
          <div className="flex items-start gap-4">
            <div className="grid flex-1 grid-cols-2 gap-x-3 gap-y-2">
              <Amount
                label={t("acquisition.planner.rows")}
                value={where.rows}
                min={1}
                step={1}
                onChange={(rows) =>
                  setWhere({ ...where, rows: Math.round(rows) })
                }
              />
              <Amount
                label={t("acquisition.planner.columns")}
                value={where.columns}
                min={1}
                step={1}
                onChange={(columns) =>
                  setWhere({ ...where, columns: Math.round(columns) })
                }
              />
              <div className="col-span-2">
                <Level
                  label={t("acquisition.planner.overlap")}
                  value={Math.round(where.overlap * 100)}
                  unit="%"
                  min={0}
                  max={50}
                  step={1}
                  onChange={(value) =>
                    setWhere({ ...where, overlap: value / 100 })
                  }
                />
              </div>
              {field && (
                <span className="col-span-2 text-[11px] text-muted-foreground">
                  {t("acquisition.planner.covers", {
                    width: length(
                      field.width *
                        (1 + (where.columns - 1) * (1 - where.overlap)),
                    ),
                    height: length(
                      field.height *
                        (1 + (where.rows - 1) * (1 - where.overlap)),
                    ),
                  })}
                </span>
              )}
            </div>
            {field && (
              <GridPreview
                rows={where.rows}
                columns={where.columns}
                overlap={where.overlap}
                field={field}
              />
            )}
          </div>
        )}
        {where.kind === "wells" && (
          <div className="space-y-3">
            <p className="text-[11px] text-muted-foreground">
              {t("acquisition.planner.wellsHint")}
            </p>
            {plates.map((plate) => {
              const wells = plate.shape?.wells.map((w) => w.name) ?? [];
              return (
                <div key={plate.sample} className="space-y-2">
                  <div className="flex items-center gap-2">
                    {plates.length > 1 && (
                      <span className="font-mono text-[11px]">
                        {plate.sample}
                      </span>
                    )}
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      className="h-6 px-2 text-[11px]"
                      onClick={() =>
                        setWhere({
                          kind: "wells",
                          wells: [...new Set([...where.wells, ...wells])],
                        })
                      }
                    >
                      {t("acquisition.planner.allWells")}
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      className="h-6 px-2 text-[11px]"
                      onClick={() =>
                        setWhere({
                          kind: "wells",
                          wells: where.wells.filter((w) => !wells.includes(w)),
                        })
                      }
                    >
                      {t("acquisition.planner.noWells")}
                    </Button>
                  </div>
                  <PlateMap
                    wells={wells}
                    picked={where.wells.filter((w) => wells.includes(w))}
                    onChange={(next) =>
                      setWhere({
                        kind: "wells",
                        wells: [
                          ...where.wells.filter((w) => !wells.includes(w)),
                          ...next,
                        ],
                      })
                    }
                  />
                </div>
              );
            })}
          </div>
        )}
        {where.kind === "spots" && (
          <div className="space-y-2">
            <p className="text-[11px] text-muted-foreground">
              {t("acquisition.planner.spotsHint")}
            </p>
            <div className="flex flex-wrap gap-1.5">
              {where.spots.map((spot, index) => (
                <span
                  key={index}
                  className="inline-flex items-center gap-1 rounded-full border border-border/60 bg-muted/40 py-0.5 pl-2.5 pr-1 text-xs"
                  title={Object.entries(spot.set_to)
                    .map(([n, v]) => `${n} ${round(v, 1)}`)
                    .join(", ")}
                >
                  {spot.name}
                  <button
                    type="button"
                    className="rounded-full p-0.5 text-muted-foreground hover:text-foreground"
                    onClick={() =>
                      setWhere({
                        kind: "spots",
                        spots: where.spots.filter((_, i) => i !== index),
                      })
                    }
                  >
                    <X className="size-3" />
                  </button>
                </span>
              ))}
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-7 px-2.5 text-xs"
                onClick={() =>
                  setWhere({
                    kind: "spots",
                    spots: [
                      ...where.spots,
                      { name: `P${where.spots.length + 1}`, set_to: here() },
                    ],
                  })
                }
              >
                <Crosshair className="mr-1 size-3" />
                {t("acquisition.planner.addHere")}
              </Button>
            </div>
          </div>
        )}
        {m.focusMoves.length > 0 && (
          <label className="flex items-center gap-2 pt-1 text-xs">
            <Switch checked={refocus} onCheckedChange={setRefocus} />
            {t("acquisition.planner.refocus")}
          </label>
        )}
      </Step>

      <Step
        index={3}
        title={t("acquisition.planner.depth")}
        aside={
          <Segmented
            value={depth.kind}
            options={[
              { value: "plane", label: t("acquisition.planner.plane") },
              { value: "stack", label: t("acquisition.planner.stack") },
            ]}
            onChange={(kind) => {
              const step =
                round(Number.isFinite(depthOfField) ? depthOfField : 1, 1) || 1;
              setDepth(
                kind === "stack"
                  ? { kind, range: step * 10, step, focus: null }
                  : { kind: "plane" },
              );
            }}
          />
        }
      >
        {stack ? (
          <div className="space-y-2">
            <div className="grid grid-cols-3 gap-3">
              <Amount
                label={t("acquisition.planner.range")}
                unit="µm"
                value={stack.range}
                onChange={(range) => setDepth({ ...stack, range })}
              />
              <Amount
                label={t("acquisition.planner.step")}
                unit="µm"
                value={drivenStep ?? stack.step}
                disabled={drivenStep != null}
                hint={
                  drivenStep != null
                    ? t("acquisition.planner.stepOfWire")
                    : undefined
                }
                min={0.01}
                step={0.1}
                onChange={(step) => setDepth({ ...stack, step })}
              />
              <div className="flex items-end pb-2 text-xs text-muted-foreground">
                {t("acquisition.planner.planesCount", {
                  count: stackOffsets(stack.range, drivenStep ?? stack.step)
                    .length,
                })}
              </div>
            </div>
            {samples.length <= 1 && m.focusMoves.length > 1 && (
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-[11px] text-muted-foreground">
                  {t("acquisition.planner.sweepWith")}
                </span>
                {m.focusMoves.map((move) => (
                  <Button
                    key={move}
                    type="button"
                    size="sm"
                    variant={stack.focus === move ? "default" : "outline"}
                    className="h-7 px-2 text-xs"
                    onClick={() => setDepth({ ...stack, focus: move })}
                  >
                    {move}
                  </Button>
                ))}
              </div>
            )}
          </div>
        ) : null}
      </Step>

      <Step
        index={4}
        title={t("acquisition.planner.time")}
        aside={
          <Segmented
            value={time.kind}
            options={[
              { value: "once", label: t("acquisition.planner.once") },
              { value: "lapse", label: t("acquisition.planner.lapse") },
            ]}
            onChange={(kind) =>
              setTime(
                kind === "lapse" ? { kind, every_s: 60, times: 10 } : { kind },
              )
            }
          />
        }
      >
        {lapse ? (
          <div className="grid grid-cols-3 gap-3">
            <Amount
              label={t("acquisition.planner.every")}
              unit="s"
              value={lapse.every_s}
              onChange={(every_s) => setTime({ ...lapse, every_s })}
            />
            <Amount
              label={t("acquisition.planner.times")}
              value={lapse.times}
              min={1}
              step={1}
              onChange={(times) =>
                setTime({ ...lapse, times: Math.round(times) })
              }
            />
            <div className="flex items-end pb-2 text-xs text-muted-foreground">
              {t("acquisition.planner.lasts", {
                duration: formatDuration((lapse.times - 1) * lapse.every_s),
              })}
            </div>
          </div>
        ) : null}
      </Step>

      <div className="sticky bottom-0 z-10 space-y-2 rounded-2xl border border-border/60 bg-background/95 p-3 shadow-lg backdrop-blur">
        {running ? (
          <>
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">
                {isLoading
                  ? task?.status === "paused"
                    ? t("acquisition.paused")
                    : t("acquisition.acquiring")
                  : task
                    ? t(`taskStatus.${task.status}`)
                    : ""}
              </span>
              {progress !== null && progress !== undefined && (
                <span className="font-mono font-semibold">
                  {Math.round(progress)}%
                </span>
              )}
            </div>
            {progress !== null && (
              <Progress value={progress} className="h-1.5" />
            )}
            {isLoading && (
              <div className="flex gap-2">
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
                    className="h-9 flex-1"
                    onClick={() => task?.id && resume(task.id)}
                  >
                    <Play className="mr-1.5 size-3.5" />
                    {t("microscope.resume")}
                  </Button>
                ) : (
                  <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    className="h-9 flex-1"
                    onClick={() => task?.id && pause(task.id)}
                  >
                    <Pause className="mr-1.5 size-3.5" />
                    {t("microscope.pause")}
                  </Button>
                )}
              </div>
            )}
          </>
        ) : null}
        {!isLoading && (
          <div className="flex items-center gap-3">
            <div className="min-w-0 flex-1 text-xs">
              {cost ? (
                <>
                  <span className="text-muted-foreground">
                    {t("acquisition.planner.summary", {
                      count: cost.exposures,
                      exposures: cost.exposures.toLocaleString(),
                      size: formatBytes(cost.bytes),
                      duration: formatDuration(cost.atLeastS),
                    })}
                  </span>
                  {cost.bytes > 4e9 && (
                    <span className="block text-warning">
                      {t("acquisition.planner.large")}
                    </span>
                  )}
                </>
              ) : (
                <span className="text-warning">{built.problem}</span>
              )}
            </div>
            <Button
              type="button"
              className="h-10 px-6"
              disabled={!built.plan}
              onClick={() =>
                built.plan && start({ plan: built.plan }, { notify: true })
              }
            >
              <Play className="mr-1.5 size-4" />
              {t("acquisition.planner.start")}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
