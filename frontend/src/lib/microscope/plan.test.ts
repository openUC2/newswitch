import { describe, expect, it } from "vitest";
import type { Detector } from "@/apps/default/hooks/states/DetectorState";
import {
  buildPlan,
  estimate,
  formatBytes,
  PlanProblem,
  stackOffsets,
  type Choices,
  type PlanContext,
} from "./plan";

const context: PlanContext = {
  swaps: { "filter_wheel.slot": 2 },
  powerVariables: {
    laser_488: "laser_488.power",
    white_led: "white_led.power",
  },
  exposureVariables: { cam_a: "cam_a.exposure", cam_b: "cam_b.exposure" },
  looking: { x: 37_500, y: 12_500 },
  field: { width: 300, height: 200 },
  samples: ["stage"],
};

const choices = (changes: Partial<Choices> = {}): Choices => ({
  name: "run",
  channels: [
    {
      source: "laser_488",
      detector: "cam_a",
      power: 20,
      exposure: 100,
      swaps: {},
    },
  ],
  alsoRecord: [],
  where: { kind: "here" },
  depth: { kind: "plane" },
  time: { kind: "once" },
  refocus: false,
  ...changes,
});

const detector = (
  name: string,
  axes: [string, number][],
  data_type = "uint16",
) =>
  ({
    name,
    data_type,
    axes: axes.map(([axis, size]) => ({ name: axis, delivered_size: size })),
  }) as unknown as Detector;

describe("buildPlan", () => {
  it("images here, once, on one plane, under the swaps as they are", () => {
    const plan = buildPlan(choices(), context);
    expect(plan.positions).toEqual([{ name: "", set_to: {} }]);
    expect(plan.stack).toEqual({ offsets: [], variable: null });
    expect(plan.channels).toEqual([
      {
        name: "laser_488",
        detectors: ["cam_a"],
        set_to: {
          "filter_wheel.slot": 2,
          "laser_488.power": 20,
          "cam_a.exposure": 100,
        },
      },
    ]);
    expect([plan.times, plan.every_s]).toEqual([1, 0]);
  });

  it("lays a grid around where the view is, row by row, every other row backwards", () => {
    const plan = buildPlan(
      choices({ where: { kind: "grid", rows: 2, columns: 3, overlap: 0.1 } }),
      context,
    );
    const at = plan.positions.map((p) => [
      p.name,
      p.at?.coordinates.x,
      p.at?.coordinates.y,
    ]);
    // Tiles a field less a tenth apart: 270 along x, 180 along y, centred where the view is.
    expect(at).toEqual([
      ["r1c1", 37_230, 12_410],
      ["r1c2", 37_500, 12_410],
      ["r1c3", 37_770, 12_410],
      ["r2c3", 37_770, 12_590],
      ["r2c2", 37_500, 12_590],
      ["r2c1", 37_230, 12_590],
    ]);
    expect(plan.positions.every((p) => p.at?.system === "sample")).toBe(true);
  });

  it("lays a grid on the one sample the plan is of, so that only its stage moves", () => {
    const plan = buildPlan(
      choices({ where: { kind: "grid", rows: 1, columns: 2, overlap: 0 } }),
      { ...context, samples: ["stage_b"], sample: "stage_b" },
    );
    expect(plan.positions.map((p) => p.at?.system)).toEqual([
      "sample:stage_b",
      "sample:stage_b",
    ]);
  });

  it("goes to wells by the graph's names, so a well is on its own sample", () => {
    const plan = buildPlan(
      choices({
        where: { kind: "wells", wells: ["well:stage:B3", "well:stage:C4"] },
      }),
      context,
    );
    expect(plan.positions.map((p) => [p.name, p.at?.system])).toEqual([
      ["B3", "well:stage:B3"],
      ["C4", "well:stage:C4"],
    ]);
  });

  it("sweeps what is named on one sample, and names nothing across two", () => {
    const stack = {
      kind: "stack",
      range: 4,
      step: 1,
      focus: "stage.z",
    } as const;
    expect(buildPlan(choices({ depth: stack }), context).stack).toEqual({
      offsets: [-2, -1, 0, 1, 2],
      variable: "stage.z",
    });
    const two = { ...context, samples: ["stage_a", "stage_b"] };
    expect(buildPlan(choices({ depth: stack }), two).stack.variable).toBeNull();
  });

  it("takes the step a detector's wire makes, whatever was asked", () => {
    const stack = { kind: "stack", range: 4, step: 1 } as const;
    const wired = { ...context, drivenStep: 2 };
    expect(buildPlan(choices({ depth: stack }), wired).stack.offsets).toEqual([
      -2, 0, 2,
    ]);
  });

  it("exposes the detectors of one source at one brightness at once, and reads a point detector with the first", () => {
    const plan = buildPlan(
      choices({
        channels: [
          {
            source: "laser_488",
            detector: "cam_a",
            power: 20,
            exposure: 100,
            swaps: {},
          },
          {
            source: "laser_488",
            detector: "cam_b",
            power: 20,
            exposure: 50,
            swaps: {},
          },
          { source: "white_led", detector: "cam_b", power: 0.01, swaps: {} },
        ],
        alsoRecord: ["thermometer"],
      }),
      context,
    );
    expect(plan.channels.map((c) => [c.name, c.detectors])).toEqual([
      ["laser_488", ["cam_a", "cam_b", "thermometer"]],
      ["white_led", ["cam_b"]],
    ]);
    expect(plan.channels[0].set_to["cam_b.exposure"]).toBe(50);
  });

  it("keeps two channels of one source apart when they take other swaps, each setting its own", () => {
    const plan = buildPlan(
      choices({
        channels: [
          {
            source: "laser_488",
            detector: "cam",
            power: 20,
            swaps: { "selector.slot": 1 },
            name: "laser_488 · arm a",
          },
          {
            source: "white_led",
            detector: "cam",
            power: 0.01,
            swaps: { "selector.slot": 2 },
          },
          {
            source: "laser_488",
            detector: "cam",
            power: 20,
            swaps: { "selector.slot": 1, "filter_wheel.slot": 3 },
          },
        ],
      }),
      context,
    );
    expect(
      plan.channels.map((c) => [
        c.name,
        c.detectors,
        c.set_to["selector.slot"],
      ]),
    ).toEqual([
      ["laser_488 · arm a", ["cam"], 1],
      ["white_led", ["cam"], 2],
      ["laser_488", ["cam"], 1],
    ]);
    expect(plan.channels[2].set_to["filter_wheel.slot"]).toBe(3);
    // What the channels do not decide stays as it is now.
    expect(plan.channels[1].set_to["filter_wheel.slot"]).toBe(2);
  });

  it("exposes detectors together only under the same swaps, in any order", () => {
    const plan = buildPlan(
      choices({
        channels: [
          {
            source: "laser_488",
            detector: "cam_a",
            power: 20,
            swaps: { a: 1, b: 2 },
          },
          {
            source: "laser_488",
            detector: "cam_b",
            power: 20,
            swaps: { b: 2, a: 1 },
          },
          {
            source: "laser_488",
            detector: "cam_c",
            power: 20,
            swaps: { a: 2, b: 2 },
          },
        ],
      }),
      context,
    );
    expect(plan.channels.map((c) => c.detectors)).toEqual([
      ["cam_a", "cam_b"],
      ["cam_c"],
    ]);
  });

  it("refuses what is no plan yet", () => {
    expect(() => buildPlan(choices({ channels: [] }), context)).toThrow(
      PlanProblem,
    );
    expect(() =>
      buildPlan(choices({ where: { kind: "wells", wells: [] } }), context),
    ).toThrow(PlanProblem);
    expect(() =>
      buildPlan(
        choices({ where: { kind: "grid", rows: 2, columns: 2, overlap: 0 } }),
        {
          ...context,
          looking: undefined,
        },
      ),
    ).toThrow(PlanProblem);
  });
});

describe("estimate", () => {
  it("counts every axis a detector delivers: arrival times make a FLIM record large", () => {
    const flim = detector("spad", [
      ["m", 64],
      ["y", 512],
      ["x", 512],
    ]);
    const plan = buildPlan(
      choices({
        channels: [
          { source: "laser_488", detector: "spad", power: 1, swaps: {} },
        ],
        depth: { kind: "stack", range: 2, step: 1 },
      }),
      context,
    );
    const found = estimate(plan, [flim], () => 10);
    expect(found.exposures).toBe(3);
    expect(found.bytes).toBe(3 * 64 * 512 * 512 * 2);
    expect(formatBytes(found.bytes)).toBe("101 MB");
  });

  it("takes at least the time-lapse, or every exposure one after another", () => {
    const camera = detector("cam_a", [
      ["y", 512],
      ["x", 512],
    ]);
    const plan = buildPlan(
      choices({ time: { kind: "lapse", every_s: 60, times: 5 } }),
      context,
    );
    expect(estimate(plan, [camera], () => 100).atLeastS).toBe(240);
  });
});

describe("stackOffsets", () => {
  it("is at least two planes, centred where it is", () => {
    expect(stackOffsets(0, 1)).toEqual([-0.5, 0.5]);
    expect(stackOffsets(3, 1.5)).toEqual([-1.5, 0, 1.5]);
  });
});
