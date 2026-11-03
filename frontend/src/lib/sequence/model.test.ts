import { describe, expect, it } from "vitest";
import {
  append,
  factsOf,
  schedule,
  sequenceText,
  starter,
  type Node,
  type Sequence,
  type States,
} from "./model";

/** An instrument as its states publish it: made up, so that nothing here is one that exists. */
const states: States = {
  moves: {
    stage: {
      x: {
        name: "stage.x",
        value: 0,
        unit: "um",
        along: "x",
        speed: 1000,
        does: ["position"],
      },
      y: {
        name: "stage.y",
        value: 0,
        unit: "um",
        along: "y",
        speed: 1000,
        does: ["position"],
      },
      z: {
        name: "stage.z",
        value: 0,
        unit: "um",
        along: "axis",
        speed: 100,
        does: ["blur"],
      },
    },
  },
  swaps: {
    wheel: {
      slot: {
        name: "wheel.slot",
        value: 1,
        label: "green",
        options: [
          { slot: 1, label: "green" },
          { slot: 2, label: "red" },
        ],
      },
    },
  },
  tunes: {
    lamp: { power: { name: "lamp.power", value: 0, unit: "mW" } },
    cam: { exposure: { name: "cam.exposure", value: 100, unit: "ms" } },
  },
  sources: {
    lamp: {
      name: "lamp",
      power_variable: "lamp.power",
      lit_power: 5,
      max_power: 10,
    },
  },
  detectors: [
    {
      name: "cam",
      quantity: "intensity",
      unit: "",
      axes: [{ name: "y" }, { name: "x" }],
    },
    {
      name: "array",
      quantity: "voltage",
      unit: "uV",
      measures_light: false,
      axes: [
        { name: "s", step: 0.05, delivered_size: 1000 },
        { name: "y" },
        { name: "x" },
      ],
    },
    {
      name: "probe",
      quantity: "temperature",
      unit: "degC",
      measures_light: false,
      axes: [],
    },
  ],
  channels: [
    {
      source: "lamp",
      detector: "cam",
      name: "Green · 500",
      sample: "stage",
      swaps: [{ variable: "wheel.slot", slot: 1, label: "green" }],
    },
    {
      source: "lamp",
      detector: "cam",
      name: "Red · 600",
      sample: "stage",
      swaps: [{ variable: "wheel.slot", slot: 2, label: "red" }],
    },
  ],
  samples: {
    stage: {
      sample: "stage",
      shape: {
        places: [
          { grid: "well", name: "well:stage:A1" },
          { grid: "well", name: "well:stage:A2" },
        ],
      },
    },
  },
  hooks: [{ type: "autofocus" }],
};

const facts = factsOf(states);
const green = facts.channels[0].ref;
const red = facts.channels[1].ref;
const expose = (id: string, channel = green): Node => ({
  id,
  kind: "expose",
  channel,
});

describe("factsOf", () => {
  it("makes a lane of every move, light, switch, detector and probe, from the states alone", () => {
    expect(facts.lanes.map((lane) => [lane.id, lane.group])).toEqual([
      ["stage.x", "stage"],
      ["stage.y", "stage"],
      ["stage.z", "stage"],
      ["lamp.power", "light"],
      ["wheel.slot", "switch"],
      ["cam", "detector"],
      ["array", "probe"],
      ["probe", "probe"],
      ["hooks", "hook"],
    ]);
    expect(facts.probes.map((p) => [p.name, p.block_s])).toEqual([
      ["array", 0.05],
      ["probe", undefined],
    ]);
    expect(facts.channels[1].exposure_s).toBe(0.1);
    expect(facts.places.map((p) => p.label)).toEqual(["well A1", "well A2"]);
  });
});

describe("schedule", () => {
  it("takes a repeat when each time is due, with what each exposure needs held beside it", () => {
    const sequence: Sequence = {
      name: "s",
      body: [
        { id: "r", kind: "repeat", times: 3, every_s: 2, body: [expose("e")] },
      ],
    };
    const { blocks, spans, conflicts } = schedule(sequence, facts);
    const on = (lane: string) =>
      blocks
        .filter((b) => b.lane === lane)
        .map((b) => [b.start, b.end, b.label]);
    expect(on("cam")).toEqual([
      [0, 0.1, "Green · 500"],
      [2, 2.1, "Green · 500"],
      [4, 4.1, "Green · 500"],
    ]);
    expect(on("wheel.slot")[1]).toEqual([2, 2.1, "green"]);
    expect(on("lamp.power")[0]).toEqual([0, 0.1, "5 mW"]);
    expect(spans[0]).toMatchObject({ start: 0, end: 4.1 });
    expect(conflicts).toEqual([]);
  });

  it("streams a probe beside the rest, as long as it all takes", () => {
    const sequence: Sequence = {
      name: "s",
      body: [
        {
          id: "p",
          kind: "parallel",
          branches: [
            [
              {
                id: "r",
                kind: "repeat",
                times: 2,
                every_s: 1,
                body: [expose("e")],
              },
            ],
            [{ id: "s", kind: "stream", probe: "array" }],
          ],
        },
      ],
    };
    const stream = schedule(sequence, facts).blocks.find(
      (b) => b.lane === "array",
    );
    expect([stream?.start, stream?.end]).toEqual([0, 1.1]);
  });

  it("finds what the instrument cannot do at once: a pulse while an exposure needs the light", () => {
    const sequence: Sequence = {
      name: "s",
      body: [
        {
          id: "p",
          kind: "parallel",
          branches: [
            [
              {
                id: "r",
                kind: "repeat",
                times: 3,
                every_s: 2,
                body: [expose("e")],
              },
            ],
            [
              {
                id: "pulse",
                kind: "set",
                variable: "lamp.power",
                value: 9,
                for_s: 0.005,
                at_s: 4,
              },
            ],
          ],
        },
      ],
    };
    const { conflicts } = schedule(sequence, facts);
    expect(conflicts.map((c) => [c.lane, c.a.start, c.b.start])).toEqual([
      ["lamp.power", 4, 4],
    ]);
  });

  it("lets two channels that want the light alike share it, and not the filter otherwise", () => {
    const sequence: Sequence = {
      name: "s",
      body: [
        {
          id: "p",
          kind: "parallel",
          branches: [[expose("a", green)], [expose("b", red)]],
        },
      ],
    };
    const lanes = schedule(sequence, facts).conflicts.map((c) => c.lane);
    expect(lanes).toContain("wheel.slot");
    expect(lanes).toContain("cam");
    expect(lanes).not.toContain("lamp.power");
  });

  it("says when a repeat cannot keep up", () => {
    const sequence: Sequence = {
      name: "s",
      body: [
        {
          id: "r",
          kind: "repeat",
          times: 2,
          every_s: 0.05,
          body: [expose("a"), expose("b", red)],
        },
      ],
    };
    expect(schedule(sequence, facts).problems[0]).toMatch(/runs late/);
  });

  it("steps the focus at each plane, as fast as it moves", () => {
    const sequence: Sequence = {
      name: "s",
      body: [
        {
          id: "z",
          kind: "for_each_z",
          range_um: 2,
          step_um: 1,
          body: [expose("e")],
        },
      ],
    };
    const z = schedule(sequence, facts).blocks.filter(
      (b) => b.lane === "stage.z",
    );
    expect(z.map((b) => b.label)).toEqual(["z -1.0", "z 0.0", "z 1.0"]);
    expect(z[0].end - z[0].start).toBeCloseTo(0.01);
  });
});

describe("a first sequence", () => {
  it("is made of what the instrument has: its probes streaming, its channels repeated", () => {
    const first = starter(facts);
    const text = sequenceText(first, facts);
    expect(text).toContain("stream: array");
    expect(text).toContain("# Green · 500");
    expect(text).toContain("read: probe");
    expect(schedule(first, facts).conflicts.length).toBeGreaterThan(0);
  });

  it("grows where it is told: a step at the end of a loop", () => {
    const body = append(
      [{ id: "r", kind: "repeat", times: 1, every_s: 0, body: [] }],
      expose("e"),
      "r",
    );
    expect(body[0]).toMatchObject({ body: [{ id: "e" }] });
  });
});
