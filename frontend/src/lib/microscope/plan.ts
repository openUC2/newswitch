import type {
  AcquisitionChannel,
  AcquisitionPlan,
  AcquisitionPosition,
} from "@/apps/default/hooks/actions/acquire";
import type { Detector } from "@/apps/default/hooks/states/DetectorState";

/**
 * An acquisition as a few choices (what to image, where, how deep, how often) and the plan they
 * make. Pure: no React, no state. What the planner shows is these choices; what the server gets is
 * `buildPlan`'s plan, in the server's terms.
 */

/** One channel the optics found (`OpticsState.channels`): a source, a detector it reaches. */
export type ChannelChoice = {
  source: string;
  detector: string;
  /** How bright the source is, in its power variable's unit (mW). */
  power: number;
  /** The detector's exposure (ms), if it has one to set. */
  exposure?: number;
};

export type GridChoice = {
  kind: "grid";
  rows: number;
  columns: number;
  /** How much neighbouring tiles share, 0 to 1. */
  overlap: number;
};

export type Where =
  | { kind: "here" }
  | GridChoice
  /** Places of what is mounted, by the graph's names: `well:stage:B3`. */
  | { kind: "wells"; wells: string[] }
  | {
      kind: "spots";
      spots: { name: string; set_to: Record<string, number> }[];
    };

export type Depth =
  | { kind: "plane" }
  | {
      kind: "stack";
      /** From the lowest plane to the highest, in micrometres. */
      range: number;
      step: number;
      /** What sweeps it, when several things focus; else what focuses. */
      focus?: string | null;
    };

export type Time =
  | { kind: "once" }
  | { kind: "lapse"; every_s: number; times: number };

export type Choices = {
  name: string;
  channels: ChannelChoice[];
  /** Detectors that measure at a point (a thermometer), read along with the first channel. */
  alsoRecord: string[];
  where: Where;
  depth: Depth;
  time: Time;
  /** Find focus again on arriving at each position. */
  refocus: boolean;
};

/** What the plan is built under: the microscope as it is now. */
export type PlanContext = {
  /** Every swap at its value now: the channels were found under them. */
  swaps: Record<string, number>;
  /** Each source's power variable, by source. */
  powerVariables: Record<string, string>;
  /** Each detector's exposure variable, by detector. */
  exposureVariables: Record<string, string>;
  /** The sample point at the middle of the view: where a grid is around. */
  looking?: { x: number; y: number };
  /** What every camera chosen sees at once, in micrometres: a grid's tile. */
  field?: { width: number; height: number };
  /** How far apart a detector's own wire steps its planes, if it does. */
  drivenStep?: number;
  /** The samples the chosen detectors see. */
  samples: string[];
};

export class PlanProblem extends Error {}

/** Where the planes of a stack of `range` micrometres, `step` apart, are: around where it is. */
export const stackOffsets = (range: number, step: number): number[] => {
  if (!(step > 0)) throw new PlanProblem("The planes need a distance apart");
  const planes = Math.max(2, Math.round(range / step) + 1);
  return Array.from(
    { length: planes },
    (_, i) => (i - (planes - 1) / 2) * step,
  );
};

/** A grid's tiles around `looking`, each a field of view apart less the overlap; row by row, every
 * other row backwards, so that the stage never runs back across the grid. */
export const gridPositions = (
  grid: GridChoice,
  looking: { x: number; y: number },
  field: { width: number; height: number },
): AcquisitionPosition[] => {
  const share = 1 - Math.min(Math.max(grid.overlap, 0), 0.9);
  const along = (index: number, count: number, size: number) =>
    (index - (count - 1) / 2) * size * share;
  const positions: AcquisitionPosition[] = [];
  for (let row = 0; row < grid.rows; row++) {
    for (let step = 0; step < grid.columns; step++) {
      const column = row % 2 === 0 ? step : grid.columns - 1 - step;
      positions.push({
        name: `r${row + 1}c${column + 1}`,
        set_to: {},
        at: {
          system: "sample",
          coordinates: {
            x: looking.x + along(column, grid.columns, field.width),
            y: looking.y + along(row, grid.rows, field.height),
          },
        },
      });
    }
  }
  return positions;
};

const positionsOf = (
  where: Where,
  context: PlanContext,
): AcquisitionPosition[] => {
  switch (where.kind) {
    case "here":
      return [{ name: "", set_to: {} }];
    case "grid":
      if (!context.looking || !context.field) {
        throw new PlanProblem("Where the view is is not known yet");
      }
      return gridPositions(where, context.looking, context.field);
    case "wells":
      if (where.wells.length === 0) throw new PlanProblem("Pick a well");
      return where.wells.map((well) => ({
        name: well.split(":").at(-1) ?? well,
        set_to: {},
        at: { system: well, coordinates: { x: 0, y: 0 } },
      }));
    case "spots":
      if (where.spots.length === 0) throw new PlanProblem("Add a place");
      return where.spots.map((spot) => ({
        name: spot.name,
        set_to: spot.set_to,
      }));
  }
};

/** The chosen channels as the plan's: those of one source at one brightness are one exposure, all
 * their detectors at once. */
const channelsOf = (
  choices: Choices,
  context: PlanContext,
): AcquisitionChannel[] => {
  const lit = new Map<string, AcquisitionChannel>();
  for (const choice of choices.channels) {
    const key = `${choice.source}@${choice.power}`;
    const power = context.powerVariables[choice.source];
    const channel = lit.get(key) ?? {
      name: choice.source,
      detectors: [],
      set_to: { ...context.swaps, ...(power ? { [power]: choice.power } : {}) },
    };
    if (!channel.detectors.includes(choice.detector))
      channel.detectors.push(choice.detector);
    const exposure = context.exposureVariables[choice.detector];
    if (exposure && choice.exposure !== undefined)
      channel.set_to[exposure] = choice.exposure;
    lit.set(key, channel);
  }
  const channels = [...lit.values()];
  if (choices.alsoRecord.length > 0) {
    if (channels.length === 0) {
      channels.push({
        name: "readings",
        detectors: [],
        set_to: { ...context.swaps },
      });
    }
    channels[0].detectors.push(...choices.alsoRecord);
  }
  if (channels.length === 0) throw new PlanProblem("Pick something to image");
  return channels;
};

/** The plan `choices` make, under `context`.
 *
 * @throws PlanProblem when the choices are no plan yet: nothing to image, no well picked.
 */
export const buildPlan = (
  choices: Choices,
  context: PlanContext,
): AcquisitionPlan => {
  const depth = choices.depth;
  const offsets =
    depth.kind === "stack"
      ? stackOffsets(depth.range, context.drivenStep ?? depth.step)
      : [];
  // Across several samples, each sweeps what focuses it: naming one would sweep only one.
  const variable =
    depth.kind === "stack" && context.samples.length <= 1
      ? (depth.focus ?? null)
      : null;
  return {
    name: choices.name || "acquisition",
    channels: channelsOf(choices, context),
    positions: positionsOf(choices.where, context),
    stack: { offsets, variable },
    times:
      choices.time.kind === "lapse"
        ? Math.max(1, Math.round(choices.time.times))
        : 1,
    every_s:
      choices.time.kind === "lapse" ? Math.max(0, choices.time.every_s) : 0,
    order: "SEQUENTIAL",
    m_hooks: [],
    t_hooks: [],
    p_hooks: choices.refocus
      ? [{ __identifier: "@newswitch/software_autofocus_hook", steps: 11 }]
      : [],
    z_hooks: [],
  } as AcquisitionPlan;
};

const BYTES: Record<string, number> = {
  uint8: 1,
  uint16: 2,
  uint32: 4,
  float32: 4,
  float64: 8,
};

/** How many values one exposure of `detector` delivers: every axis but its planes, as read out. */
export const valuesPerExposure = (detector: Detector): number =>
  detector.axes
    .filter((axis) => axis.name !== "z")
    .reduce((count, axis) => count * (axis.delivered_size ?? 1), 1);

export type Estimate = {
  /** Exposures of all detectors. */
  exposures: number;
  bytes: number;
  /** At least this long: the time-lapse, and every exposure one after the other. */
  atLeastS: number;
  planes: number;
  positions: number;
  times: number;
};

/** What a plan takes: exposures, bytes held until written, and a floor for how long. */
export const estimate = (
  plan: AcquisitionPlan,
  detectors: Detector[],
  exposureMs: (detector: string, channel: AcquisitionChannel) => number,
): Estimate => {
  const byName = new Map(detectors.map((d) => [d.name, d]));
  const planes = Math.max(1, plan.stack.offsets.length);
  const positions = plan.positions.length;
  const times = plan.times;
  const visits = planes * positions * times;
  let exposures = 0;
  let bytes = 0;
  let exposingS = 0;
  for (const channel of plan.channels) {
    for (const name of channel.detectors) {
      const detector = byName.get(name);
      if (!detector) continue;
      exposures += visits;
      bytes +=
        visits * valuesPerExposure(detector) * (BYTES[detector.data_type] ?? 2);
    }
    exposingS +=
      (visits *
        Math.max(
          0,
          ...channel.detectors.map((name) => exposureMs(name, channel)),
        )) /
      1000;
  }
  const lapseS = (times - 1) * plan.every_s;
  return {
    exposures,
    bytes,
    atLeastS: Math.max(lapseS, exposingS),
    planes,
    positions,
    times,
  };
};

/** `bytes` as people read them. */
export const formatBytes = (bytes: number): string => {
  const units = ["B", "kB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1000 && unit < units.length - 1) {
    value /= 1000;
    unit++;
  }
  return `${value < 10 && unit > 0 ? value.toFixed(1) : Math.round(value)} ${units[unit]}`;
};

/** `seconds` as people read them. */
export const formatDuration = (seconds: number): string => {
  if (seconds < 60) return `${Math.max(1, Math.round(seconds))} s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.round((seconds % 3600) / 60);
  return minutes ? `${hours} h ${minutes} min` : `${hours} h`;
};
