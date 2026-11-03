/**
 * A sequence: what to do, in what order and when, as a document a power user can write and read.
 *
 * Nothing in here knows a microscope. What there is to do it with (`Facts`) is read from the
 * instrument's published states: its moves, swaps, sources, detectors and probes, the channels the
 * optics found, the places of what is mounted, the hooks registered. A sequence names those, and
 * `schedule` lays it out on one clock, lane by lane: a lane is a variable or a detector, as the
 * instrument has them. Pure: no React, no state.
 */

// ----------------------------------------------------------------- what the instrument offers

export type LaneGroup =
  | "stage"
  | "move"
  | "light"
  | "switch"
  | "tune"
  | "detector"
  | "probe"
  | "hook";

/** A row of the timeline: something that does one thing at a time. */
export type Lane = {
  id: string;
  group: LaneGroup;
  label: string;
  /** The sample it is of, where it is of one. */
  sample?: string;
  unit?: string;
};

/** A channel, by what makes it: its source, its detector and the swaps that decide it. Names are
 * shown, never stored: they follow the naming rules, and change with them. */
export type ChannelRef = {
  source: string;
  detector: string;
  swaps: Record<string, number>;
};

export type ChannelFact = {
  ref: ChannelRef;
  name: string;
  sample: string;
  /** How long the detector exposes now, in seconds. */
  exposure_s?: number;
  /** The variable that tunes the source, and what it is at when lit. */
  power?: { variable: string; value: number; unit: string };
  swapLabels: Record<string, string>;
};

export type ProbeFact = {
  name: string;
  quantity: string;
  unit: string;
  sample?: string;
  /** How long a block of its samples in time is, if it samples time. */
  block_s?: number;
};

export type PlaceFact = { system: string; label: string; sample: string };

export type MoveFact = {
  variable: string;
  cube: string;
  along: string;
  value: number;
  unit: string;
  /** In its unit a second, where the description says. */
  speed?: number;
  /** What moving it does, as the server found: position, blur, scale, ... */
  does: string[];
};

export type SetFact = {
  variable: string;
  label: string;
  unit: string;
  value: number;
  /** A swap's slots; none for a value. */
  options?: { slot: number; label: string }[];
  lane: string;
};

export type Facts = {
  lanes: Lane[];
  channels: ChannelFact[];
  probes: ProbeFact[];
  places: PlaceFact[];
  moves: MoveFact[];
  sets: SetFact[];
  hooks: string[];
  samples: string[];
};

// ----------------------------------------------------------------- the document

type Base = { id: string };

export type Expose = Base & {
  kind: "expose";
  channel: ChannelRef;
  at_s?: number;
};
export type Read = Base & { kind: "read"; probe: string; at_s?: number };
export type Stream = Base & { kind: "stream"; probe: string };
export type SetValue = Base & {
  kind: "set";
  variable: string;
  value: number;
  /** Held this long, then back to what it was: a pulse. None: it stays. */
  for_s?: number;
  at_s?: number;
};
export type MoveTo = Base & { kind: "move"; to: string; at_s?: number };
export type Hook = Base & { kind: "hook"; hook: string };
export type Wait = Base & { kind: "wait"; for_s: number };

export type Repeat = Base & {
  kind: "repeat";
  times: number;
  every_s: number;
  body: Node[];
};
export type ForEachPosition = Base & {
  kind: "for_each_position";
  places: string[];
  body: Node[];
};
export type ForEachZ = Base & {
  kind: "for_each_z";
  range_um: number;
  step_um: number;
  body: Node[];
};
export type Parallel = Base & { kind: "parallel"; branches: Node[][] };

export type Step = Expose | Read | Stream | SetValue | MoveTo | Hook | Wait;
export type Loop = Repeat | ForEachPosition | ForEachZ;
export type Node = Step | Loop | Parallel;

export type Sequence = { name: string; body: Node[] };

let counter = 0;
/** A fresh id for a node. */
export const newId = (): string =>
  `n${Date.now().toString(36)}${(counter++).toString(36)}`;

export const sameChannel = (a: ChannelRef, b: ChannelRef): boolean =>
  a.source === b.source &&
  a.detector === b.detector &&
  JSON.stringify(Object.entries(a.swaps).sort()) ===
    JSON.stringify(Object.entries(b.swaps).sort());

// ----------------------------------------------------------------- reading the instrument

/** The published states, as `Facts` reads them: only what it needs. */
export type States = {
  moves?: Record<
    string,
    Record<
      string,
      {
        name: string;
        value: number;
        unit: string;
        along: string;
        speed?: number | null;
        does?: string[];
      }
    >
  >;
  swaps?: Record<
    string,
    Record<
      string,
      {
        name: string;
        value: number;
        label: string;
        options?: { slot: number; label: string }[];
      }
    >
  >;
  tunes?: Record<
    string,
    Record<string, { name: string; value: number; unit: string }>
  >;
  sources?: Record<
    string,
    {
      name: string;
      power_variable?: string | null;
      lit_power: number;
      max_power: number;
    }
  >;
  detectors?: {
    name: string;
    quantity: string;
    unit: string;
    measures_light?: boolean;
    axes: {
      name: string;
      step?: number | null;
      delivered_size?: number | null;
      size?: number | null;
    }[];
  }[];
  channels?: {
    source: string;
    detector: string;
    name: string;
    sample: string;
    swaps?: { variable: string; slot: number; label: string }[];
  }[];
  samples?: Record<
    string,
    {
      sample: string;
      shape?: { places?: { grid: string; name: string }[] } | null;
    }
  >;
  points?: Record<string, { sample: string }>;
  placements?: Record<string, { sample: string }>;
  hooks?: { type: string }[];
};

/** What there is to do things with, and the lanes they happen on: all from the states. */
export const factsOf = (states: States): Facts => {
  const samples = Object.keys(states.samples ?? {});
  const lanes: Lane[] = [];
  const moves: MoveFact[] = [];
  for (const [cube, byVariable] of Object.entries(states.moves ?? {})) {
    for (const move of Object.values(byVariable)) {
      const sample = samples.includes(cube) ? cube : undefined;
      lanes.push({
        id: move.name,
        group: sample ? "stage" : "move",
        label: move.name,
        sample,
        unit: move.unit,
      });
      moves.push({
        variable: move.name,
        cube,
        along: move.along,
        value: move.value,
        unit: move.unit,
        speed: move.speed ?? undefined,
        does: move.does ?? [],
      });
    }
  }
  const sets: SetFact[] = [];
  const powerOf = new Map<string, string>();
  for (const source of Object.values(states.sources ?? {})) {
    if (!source.power_variable) continue;
    powerOf.set(source.name, source.power_variable);
    lanes.push({
      id: source.power_variable,
      group: "light",
      label: source.name,
      unit: "mW",
    });
  }
  for (const byVariable of Object.values(states.swaps ?? {})) {
    for (const swap of Object.values(byVariable)) {
      lanes.push({ id: swap.name, group: "switch", label: swap.name });
      sets.push({
        variable: swap.name,
        label: swap.name,
        unit: "",
        value: swap.value,
        options: swap.options?.map(({ slot, label }) => ({ slot, label })),
        lane: swap.name,
      });
    }
  }
  const exposureOf = new Map<string, number>();
  for (const [cube, byVariable] of Object.entries(states.tunes ?? {})) {
    for (const tune of Object.values(byVariable)) {
      if (tune.name === `${cube}.exposure`)
        exposureOf.set(cube, tune.value / 1000);
      const isPower = [...powerOf.values()].includes(tune.name);
      if (isPower) {
        sets.push({
          variable: tune.name,
          label: tune.name,
          unit: tune.unit,
          value: tune.value,
          lane: tune.name,
        });
      }
    }
  }
  const probes: ProbeFact[] = [];
  for (const detector of states.detectors ?? []) {
    const probe = detector.measures_light === false;
    const sample =
      states.placements?.[detector.name]?.sample ??
      states.points?.[detector.name]?.sample;
    lanes.push({
      id: detector.name,
      group: probe ? "probe" : "detector",
      label: detector.name,
      sample,
      unit: detector.unit,
    });
    if (probe) {
      const s = detector.axes.find((axis) => axis.name === "s");
      const size = s?.delivered_size ?? s?.size;
      probes.push({
        name: detector.name,
        quantity: detector.quantity,
        unit: detector.unit,
        sample,
        block_s: s?.step && size ? (size * s.step) / 1000 : undefined,
      });
    }
  }
  const sourcesByName = new Map(
    Object.values(states.sources ?? {}).map((s) => [s.name, s]),
  );
  const channels: ChannelFact[] = (states.channels ?? []).map((channel) => {
    const source = sourcesByName.get(channel.source);
    const variable = powerOf.get(channel.source);
    return {
      ref: {
        source: channel.source,
        detector: channel.detector,
        swaps: Object.fromEntries(
          (channel.swaps ?? []).map((s) => [s.variable, s.slot]),
        ),
      },
      name: channel.name,
      sample: channel.sample,
      exposure_s: exposureOf.get(channel.detector),
      power:
        variable && source
          ? {
              variable,
              value: source.lit_power || source.max_power,
              unit: "mW",
            }
          : undefined,
      swapLabels: Object.fromEntries(
        (channel.swaps ?? []).map((s) => [s.variable, s.label]),
      ),
    };
  });
  const places: PlaceFact[] = Object.values(states.samples ?? {}).flatMap(
    (space) =>
      (space.shape?.places ?? []).map((place) => ({
        system: place.name,
        // its grid and its name: a chip's well A1 is not its electrode A1
        label: `${place.grid} ${place.name.split(":").slice(-1)[0] ?? place.name}`,
        sample: space.sample,
      })),
  );
  lanes.push({ id: "hooks", group: "hook", label: "hooks" });
  const order: LaneGroup[] = [
    "stage",
    "move",
    "light",
    "switch",
    "tune",
    "detector",
    "probe",
    "hook",
  ];
  lanes.sort((a, b) => order.indexOf(a.group) - order.indexOf(b.group));
  return {
    lanes,
    channels,
    probes,
    places,
    moves,
    sets,
    hooks: (states.hooks ?? []).map((hook) => hook.type),
    samples,
  };
};

/** What focuses a sample: its moves along the axis that blur and do not scale. */
export const focusOf = (facts: Facts, sample?: string): MoveFact | undefined =>
  facts.moves.find(
    (move) =>
      move.along === "axis" &&
      move.does.includes("blur") &&
      !move.does.includes("scale") &&
      (sample === undefined || move.cube === sample),
  );

/** A first sequence, for whatever instrument it is: every probe that samples time streaming the
 * whole time; beside it, a few times over, the first channels of the first sample; and one probe
 * at a point read with them. Nothing here names a part. */
export const starter = (facts: Facts): Sequence => {
  const sample = facts.samples[0];
  const channels = facts.channels
    .filter((c) => c.sample === sample)
    .slice(0, 2);
  const streams = facts.probes.filter((p) => p.block_s !== undefined);
  const points = facts.probes
    .filter((p) => p.block_s === undefined)
    .slice(0, 1);
  const pulse = facts.sets.find((set) => set.lane.endsWith(".power"));
  const imaging: Node = {
    id: newId(),
    kind: "repeat",
    times: 5,
    every_s: 2,
    body: [
      ...channels.map(
        (c): Node => ({ id: newId(), kind: "expose", channel: c.ref }),
      ),
      ...points.map(
        (p): Node => ({ id: newId(), kind: "read", probe: p.name }),
      ),
    ],
  };
  const branches: Node[][] = [[imaging]];
  for (const probe of streams)
    branches.push([{ id: newId(), kind: "stream", probe: probe.name }]);
  if (pulse) {
    branches.push([
      {
        id: newId(),
        kind: "set",
        variable: pulse.variable,
        value:
          channels.find((c) => c.power?.variable === pulse.variable)?.power
            ?.value ?? 1,
        for_s: 0.005,
        at_s: 4,
      },
    ]);
  }
  return {
    name: "sequence",
    body:
      branches.length > 1
        ? [{ id: newId(), kind: "parallel", branches }]
        : [imaging],
  };
};

// ----------------------------------------------------------------- laying it out on one clock

export type Block = {
  node: string;
  lane: string;
  start: number;
  end: number;
  label: string;
  /** What another block needs held while it happens (a channel's light and switches). */
  condition?: boolean;
  /** What it is set to there, for telling two apart. */
  value?: string;
  /** How long it takes is not known before it runs. */
  unknown?: boolean;
  /** Pinned to the clock, and the sequence before it is not done by then. */
  late?: boolean;
};

export type Span = {
  node: string;
  label: string;
  start: number;
  /** Its first time through, laid out in full. */
  firstEnd: number;
  /** All of it, every time through. */
  end: number;
  depth: number;
};

export type Conflict = { lane: string; a: Block; b: Block };

export type Schedule = {
  blocks: Block[];
  spans: Span[];
  conflicts: Conflict[];
  end: number;
  problems: string[];
};

/** How long something whose duration is not known is drawn: a mark, not a guess. */
export const UNKNOWN_S = 0.05;
/** How long something instant is drawn. */
const INSTANT_S = 0.02;
/** How many blocks are laid out before the rest of a loop is only counted. */
const BUDGET = 4000;

export const channelOf = (
  facts: Facts,
  ref: ChannelRef,
): ChannelFact | undefined =>
  facts.channels.find((c) => sameChannel(c.ref, ref));

/** Lay `sequence` out on one clock: every step of the first time through each loop in full, each
 * loop as a span as long as all of it, every block on its lane; and where two blocks on one lane
 * overlap and want it otherwise, a conflict. */
export const schedule = (sequence: Sequence, facts: Facts): Schedule => {
  const blocks: Block[] = [];
  const spans: Span[] = [];
  const problems: string[] = [];
  const streams: {
    node: string;
    lane: string;
    start: number;
    label: string;
    until: number[];
  }[] = [];

  const step = (node: Step, at: number): number => {
    const start = "at_s" in node && node.at_s !== undefined ? node.at_s : at;
    const late =
      "at_s" in node && node.at_s !== undefined && node.at_s < at - 1e-9;
    switch (node.kind) {
      case "expose": {
        const channel = channelOf(facts, node.channel);
        if (!channel) {
          problems.push(
            `${node.channel.source} → ${node.channel.detector}: no such channel on this instrument`,
          );
          return start;
        }
        const length = channel.exposure_s ?? UNKNOWN_S;
        const end = start + length;
        blocks.push({
          node: node.id,
          lane: node.channel.detector,
          start,
          end,
          label: channel.name,
          unknown: channel.exposure_s === undefined,
          late,
        });
        if (channel.power) {
          blocks.push({
            node: node.id,
            lane: channel.power.variable,
            start,
            end,
            label: `${channel.power.value} ${channel.power.unit}`,
            value: `${channel.power.value}`,
            condition: true,
          });
        }
        for (const [variable, slot] of Object.entries(node.channel.swaps)) {
          blocks.push({
            node: node.id,
            lane: variable,
            start,
            end,
            label: channel.swapLabels[variable] ?? `${slot}`,
            value: `${slot}`,
            condition: true,
          });
        }
        return end;
      }
      case "read": {
        const probe = facts.probes.find((p) => p.name === node.probe);
        const length = probe?.block_s ?? INSTANT_S;
        blocks.push({
          node: node.id,
          lane: node.probe,
          start,
          end: start + length,
          label: "read",
          late,
        });
        return start + length;
      }
      case "stream": {
        streams.push({
          node: node.id,
          lane: node.probe,
          start,
          label: "stream",
          until: [],
        });
        return start;
      }
      case "set": {
        const set = facts.sets.find((s) => s.variable === node.variable);
        const length = node.for_s ?? INSTANT_S;
        const label =
          set?.options?.find((o) => o.slot === node.value)?.label ??
          `${node.value}${set?.unit ? ` ${set.unit}` : ""}`;
        blocks.push({
          node: node.id,
          lane: node.variable,
          start,
          end: start + length,
          label:
            node.for_s !== undefined
              ? `${label} for ${node.for_s * 1000} ms`
              : `→ ${label}`,
          value: `${node.value}`,
          late,
        });
        return node.for_s !== undefined ? start : start + length;
      }
      case "move": {
        const place = facts.places.find((p) => p.system === node.to);
        const lanes = facts.moves.filter(
          (m) =>
            (m.along === "x" || m.along === "y") &&
            m.does.includes("position") &&
            (place === undefined || m.cube === place.sample),
        );
        for (const move of lanes) {
          blocks.push({
            node: node.id,
            lane: move.variable,
            start,
            end: start + UNKNOWN_S,
            label: `→ ${place?.label ?? node.to}`,
            unknown: true,
            late,
          });
        }
        return start + UNKNOWN_S;
      }
      case "hook": {
        blocks.push({
          node: node.id,
          lane: "hooks",
          start,
          end: start + UNKNOWN_S,
          label: node.hook,
          unknown: true,
        });
        return start + UNKNOWN_S;
      }
      case "wait":
        return start + node.for_s;
    }
  };

  const run = (nodes: Node[], at: number, depth: number): number => {
    let cursor = at;
    for (const node of nodes) cursor = one(node, cursor, depth);
    return cursor;
  };

  const one = (node: Node, at: number, depth: number): number => {
    switch (node.kind) {
      case "parallel": {
        const before = streams.length;
        const ends = node.branches.map((branch) => run(branch, at, depth));
        const end = Math.max(at, ...ends);
        // what streams in a branch records as long as the others take
        for (const open of streams.splice(before)) {
          blocks.push({
            node: open.node,
            lane: open.lane,
            start: open.start,
            end,
            label: open.label,
          });
        }
        return end;
      }
      case "repeat": {
        let cursor = at;
        let firstEnd = at;
        let late = false;
        for (let k = 0; k < Math.max(1, node.times); k++) {
          const due = at + k * node.every_s;
          if (cursor > due + 1e-9) late = true;
          const begin = Math.max(due, cursor);
          if (blocks.length > BUDGET) {
            // too much to draw: what is left, as long as the first took
            cursor =
              begin + (node.times - k) * Math.max(node.every_s, firstEnd - at);
            break;
          }
          cursor = run(node.body, begin, depth + 1);
          if (k === 0) firstEnd = cursor;
        }
        if (late) {
          problems.push(
            `Repeat every ${node.every_s} s takes ${(firstEnd - at).toFixed(2)} s a time: it runs late`,
          );
        }
        spans.push({
          node: node.id,
          label: `repeat ×${node.times} every ${node.every_s} s`,
          start: at,
          firstEnd,
          end: cursor,
          depth,
        });
        return cursor;
      }
      case "for_each_position": {
        let cursor = at;
        let firstEnd = at;
        const places = node.places.length ? node.places : ["here"];
        for (const [k, place] of places.entries()) {
          if (blocks.length > BUDGET) {
            cursor += (places.length - k) * (firstEnd - at);
            break;
          }
          cursor = run(
            [{ id: `${node.id}:${k}`, kind: "move", to: place }, ...node.body],
            cursor,
            depth + 1,
          );
          if (k === 0) firstEnd = cursor;
        }
        spans.push({
          node: node.id,
          label: `each of ${node.places.length} places`,
          start: at,
          firstEnd,
          end: cursor,
          depth,
        });
        return cursor;
      }
      case "for_each_z": {
        const planes = Math.max(
          2,
          Math.round(node.range_um / node.step_um) + 1,
        );
        // what focuses the sample its channels are of
        const exposed = walk(node.body).find(
          (n): n is Expose => n.kind === "expose",
        );
        const sample = exposed
          ? channelOf(facts, exposed.channel)?.sample
          : facts.samples[0];
        const focus = focusOf(facts, sample);
        if (!focus)
          problems.push("Nothing here focuses: a z loop has nothing to move");
        let cursor = at;
        let firstEnd = at;
        for (let k = 0; k < planes; k++) {
          if (blocks.length > BUDGET) {
            cursor += (planes - k) * (firstEnd - at);
            break;
          }
          if (focus) {
            const length = focus.speed ? node.step_um / focus.speed : UNKNOWN_S;
            blocks.push({
              node: node.id,
              lane: focus.variable,
              start: cursor,
              end: cursor + length,
              label: `z ${(-node.range_um / 2 + k * node.step_um).toFixed(1)}`,
              unknown: !focus.speed,
            });
            cursor += length;
          }
          cursor = run(node.body, cursor, depth + 1);
          if (k === 0) firstEnd = cursor;
        }
        spans.push({
          node: node.id,
          label: `each of ${planes} planes, ${node.step_um} µm apart`,
          start: at,
          firstEnd,
          end: cursor,
          depth,
        });
        return cursor;
      }
      default:
        return step(node, at);
    }
  };

  const end = run(sequence.body, 0, 0);
  for (const open of streams) {
    blocks.push({
      node: open.node,
      lane: open.lane,
      start: open.start,
      end,
      label: open.label,
    });
  }

  // two blocks on one lane at once that want it otherwise: what the instrument cannot do
  const conflicts: Conflict[] = [];
  const byLane = new Map<string, Block[]>();
  for (const block of blocks)
    byLane.set(block.lane, [...(byLane.get(block.lane) ?? []), block]);
  for (const [lane, onIt] of byLane) {
    for (let i = 0; i < onIt.length; i++) {
      for (let j = i + 1; j < onIt.length; j++) {
        const a = onIt[i];
        const b = onIt[j];
        const overlap = a.start < b.end - 1e-9 && b.start < a.end - 1e-9;
        const alike = a.condition && b.condition && a.value === b.value;
        if (overlap && !alike && a.node !== b.node)
          conflicts.push({ lane, a, b });
      }
    }
  }
  return {
    blocks,
    spans,
    conflicts,
    end: Math.max(end, ...blocks.map((b) => b.end)),
    problems,
  };
};

// ----------------------------------------------------------------- as text

/** A node as the document says it, ids left out. */
const plain = (node: Node, facts: Facts): unknown => {
  switch (node.kind) {
    case "expose": {
      const name = channelOf(facts, node.channel)?.name;
      return {
        expose: {
          source: node.channel.source,
          detector: node.channel.detector,
          ...(Object.keys(node.channel.swaps).length
            ? { swaps: node.channel.swaps }
            : {}),
          ...(node.at_s !== undefined ? { at: `${node.at_s} s` } : {}),
        },
        ...(name ? { "#": name } : {}),
      };
    }
    case "read":
      return {
        read: node.probe,
        ...(node.at_s !== undefined ? { at: `${node.at_s} s` } : {}),
      };
    case "stream":
      return { stream: node.probe };
    case "set":
      return {
        set: { [node.variable]: node.value },
        ...(node.for_s !== undefined ? { for: `${node.for_s * 1000} ms` } : {}),
        ...(node.at_s !== undefined ? { at: `${node.at_s} s` } : {}),
      };
    case "move":
      return {
        move_to: node.to,
        ...(node.at_s !== undefined ? { at: `${node.at_s} s` } : {}),
      };
    case "hook":
      return { hook: node.hook };
    case "wait":
      return { wait: `${node.for_s} s` };
    case "repeat":
      return {
        repeat: { times: node.times, every: `${node.every_s} s` },
        do: node.body.map((n) => plain(n, facts)),
      };
    case "for_each_position":
      return {
        for_each_position: node.places,
        do: node.body.map((n) => plain(n, facts)),
      };
    case "for_each_z":
      return {
        for_each_z: {
          range: `${node.range_um} um`,
          step: `${node.step_um} um`,
        },
        do: node.body.map((n) => plain(n, facts)),
      };
    case "parallel":
      return {
        parallel: node.branches.map((branch) =>
          branch.map((n) => plain(n, facts)),
        ),
      };
  }
};

const scalar = (value: unknown): string => {
  if (typeof value === "number" || typeof value === "boolean")
    return String(value);
  const text = String(value);
  return /^[\w.\-/ ]+$/.test(text) && !/^\d/.test(text) && !text.includes(": ")
    ? text
    : JSON.stringify(text);
};

/** `value` as YAML: plain data only, no anchors, keys in the order given. */
export const toYaml = (value: unknown, indent = 0): string => {
  const pad = " ".repeat(indent);
  if (Array.isArray(value)) {
    if (value.length === 0) return `${pad}[]`;
    return value
      .map((item) => {
        if (item !== null && typeof item === "object") {
          const inner = toYaml(item, indent + 2).trimStart();
          return `${pad}- ${inner}`;
        }
        return `${pad}- ${scalar(item)}`;
      })
      .join("\n");
  }
  if (value !== null && typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, item]) => {
        const name = key === "#" ? "#" : key;
        if (key === "#") return `${pad}# ${String(item)}`;
        if (item !== null && typeof item === "object") {
          const empty = Array.isArray(item)
            ? item.length === 0
            : Object.keys(item).length === 0;
          if (empty)
            return `${pad}${name}: ${Array.isArray(item) ? "[]" : "{}"}`;
          return `${pad}${name}:\n${toYaml(item, indent + 2)}`;
        }
        return `${pad}${name}: ${scalar(item)}`;
      })
      .join("\n");
  }
  return `${pad}${scalar(value)}`;
};

/** The whole sequence as the text a power user would write. */
export const sequenceText = (sequence: Sequence, facts: Facts): string =>
  toYaml({ sequence: sequence.body.map((node) => plain(node, facts)) });

// ----------------------------------------------------------------- editing

/** Every node of `nodes`, depth first. */
export const walk = (nodes: Node[]): Node[] =>
  nodes.flatMap((node) => [node, ...walk(childrenOf(node))]);

/** What a loop or a parallel holds; none for a step. */
export const childrenOf = (node: Node): Node[] =>
  node.kind === "parallel"
    ? node.branches.flat()
    : "body" in node
      ? node.body
      : [];

/** `nodes` with the node `id` changed by `change` (or taken out, if it returns null). */
export const update = (
  nodes: Node[],
  id: string,
  change: (node: Node) => Node | null,
): Node[] =>
  nodes.flatMap((node): Node[] => {
    if (node.id === id) {
      const next = change(node);
      return next ? [next] : [];
    }
    if (node.kind === "parallel") {
      return [
        { ...node, branches: node.branches.map((b) => update(b, id, change)) },
      ];
    }
    if ("body" in node)
      return [{ ...node, body: update(node.body, id, change) } as Node];
    return [node];
  });

/** `nodes` with `added` put at the end of what `into` holds: a loop's body, a parallel's last
 * branch, or (no `into`) the sequence itself. */
export const append = (nodes: Node[], added: Node, into?: string): Node[] =>
  into === undefined
    ? [...nodes, added]
    : update(nodes, into, (node) => {
        if (node.kind === "parallel") {
          const branches = node.branches.length ? node.branches : [[]];
          return {
            ...node,
            branches: [
              ...branches.slice(0, -1),
              [...branches[branches.length - 1], added],
            ],
          };
        }
        if ("body" in node)
          return { ...node, body: [...node.body, added] } as Node;
        return node;
      });

/** `nodes` with the node `id` one place earlier (-1) or later (+1) among its siblings. */
export const shift = (nodes: Node[], id: string, by: -1 | 1): Node[] => {
  const index = nodes.findIndex((n) => n.id === id);
  if (index >= 0) {
    const to = index + by;
    if (to < 0 || to >= nodes.length) return nodes;
    const next = [...nodes];
    [next[index], next[to]] = [next[to], next[index]];
    return next;
  }
  return nodes.map((node) => {
    if (node.kind === "parallel") {
      return { ...node, branches: node.branches.map((b) => shift(b, id, by)) };
    }
    if ("body" in node)
      return { ...node, body: shift(node.body, id, by) } as Node;
    return node;
  });
};
