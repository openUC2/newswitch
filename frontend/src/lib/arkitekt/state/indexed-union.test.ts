import { describe, expect, it } from "vitest";
import { z } from "zod";
import {
  KubeUnionSchema,
  LightPathStateSchema,
} from "@/apps/default/hooks/states/LightPathState";

/**
 * arkitekt serializes a union value as a positional envelope - `{ __use: <variant index>, __value: ... }`
 * - and requires the same shape back on the way in. The generated `createIndexedUnion` codec is what
 * bridges that to the flat model objects the UI consumes, so both directions are pinned down here.
 */

const objectiveKubeWire = {
  __use: 0,
  __value: {
    __identifier: "@newswitch/objective_kube",
    kube_id: "obj-1",
    slot_id: 3,
    affine_matrix: [
      [1, 0],
      [0, 1],
    ],
    model_name: "Plan-Apochromat 63x",
    model_file: null,
  },
};

const filterKubeWire = {
  __use: 2,
  __value: {
    __identifier: "@newswitch/filter_kube",
    kube_id: "flt-1",
    wavelength: 525,
    affine_matrix: [
      [1, 0],
      [0, 1],
    ],
  },
};

const lightPathStateWire = {
  light_paths: [
    {
      __identifier: "@newswitch/light_path",
      detector: 0,
      kubes: [objectiveKubeWire, filterKubeWire],
      edges: [],
    },
  ],
  current_light_path: null,
};

describe("createIndexedUnion", () => {
  it("decodes the union envelope into a flat model", () => {
    const parsed = LightPathStateSchema.parse(lightPathStateWire);
    const kubes = parsed.light_paths[0].kubes;

    // The scene graph reads kube.kube_id / kube.__identifier straight off the kube.
    expect(kubes.map((kube) => kube.kube_id)).toEqual(["obj-1", "flt-1"]);
    expect(kubes.map((kube) => kube.__identifier)).toEqual([
      "@newswitch/objective_kube",
      "@newswitch/filter_kube",
    ]);
    expect(kubes[0]).not.toHaveProperty("__use");
  });

  it("decodes an already-decoded value unchanged", () => {
    // Patch values are spliced into a decoded document, so decode has to be idempotent.
    const once = LightPathStateSchema.parse(lightPathStateWire);
    expect(LightPathStateSchema.parse(once)).toEqual(once);
  });

  it("encodes a flat model back into the positional envelope", () => {
    const flat = KubeUnionSchema.parse(filterKubeWire);
    const encoded = z.encode(KubeUnionSchema, flat);

    // 2 is FilterKube's position in the backend's union, and the index is the only thing
    // the backend discriminates on.
    expect(encoded).toMatchObject({
      __use: 2,
      __value: { kube_id: "flt-1", wavelength: 525 },
    });
  });

  it("round-trips a value through decode and encode", () => {
    const flat = KubeUnionSchema.parse(objectiveKubeWire);
    expect(z.encode(KubeUnionSchema, flat)).toEqual(objectiveKubeWire);
  });

  it("rejects an envelope whose payload matches no variant", () => {
    expect(
      KubeUnionSchema.safeParse({ __use: 0, __value: { bogus: true } }).success,
    ).toBe(false);
  });
});
