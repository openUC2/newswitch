import { describe, expect, it } from "vitest";
import { z } from "zod";
import { createIndexedUnion } from "@/apps/default/hooks/states/utils";

/**
 * arkitekt serializes a union value as a positional envelope - `{ __use: <variant index>,
 * __value: <payload> }` - and requires the same shape back on the way in. The generated
 * `createIndexedUnion` codec bridges that to the flat model objects the UI consumes, so both
 * directions are pinned down here.
 */

const LensSchema = z.object({
  __identifier: z.literal("@test/lens"),
  name: z.string(),
  na: z.number(),
});
const SourceSchema = z.object({
  __identifier: z.literal("@test/source"),
  name: z.string(),
  wavelength: z.number(),
});
const FilterSchema = z.object({
  __identifier: z.literal("@test/filter"),
  name: z.string(),
  center: z.number(),
});
const ElementUnionSchema = createIndexedUnion([
  LensSchema,
  SourceSchema,
  FilterSchema,
]);
const PathSchema = z.object({ elements: z.array(ElementUnionSchema) });

const lensWire = {
  __use: 0,
  __value: { __identifier: "@test/lens", name: "objective", na: 0.25 },
};
const filterWire = {
  __use: 2,
  __value: { __identifier: "@test/filter", name: "gfp", center: 525 },
};
const pathWire = { elements: [lensWire, filterWire] };

describe("createIndexedUnion", () => {
  it("decodes the union envelope into a flat model", () => {
    const { elements } = PathSchema.parse(pathWire);

    expect(elements.map((element) => element.name)).toEqual([
      "objective",
      "gfp",
    ]);
    expect(elements.map((element) => element.__identifier)).toEqual([
      "@test/lens",
      "@test/filter",
    ]);
    expect(elements[0]).not.toHaveProperty("__use");
  });

  it("decodes an already-decoded value unchanged", () => {
    // Patch values are spliced into a decoded document, so decode has to be idempotent.
    const once = PathSchema.parse(pathWire);
    expect(PathSchema.parse(once)).toEqual(once);
  });

  it("encodes a flat model back into the positional envelope", () => {
    const flat = ElementUnionSchema.parse(filterWire);

    // 2 is the filter's position in the union, and the index is the only thing the backend
    // discriminates on.
    expect(z.encode(ElementUnionSchema, flat)).toMatchObject({
      __use: 2,
      __value: { name: "gfp", center: 525 },
    });
  });

  it("round-trips a value through decode and encode", () => {
    const flat = ElementUnionSchema.parse(lensWire);
    expect(z.encode(ElementUnionSchema, flat)).toEqual(lensWire);
  });

  it("rejects an envelope whose payload matches no variant", () => {
    expect(
      ElementUnionSchema.safeParse({ __use: 0, __value: { bogus: true } })
        .success,
    ).toBe(false);
  });
});
