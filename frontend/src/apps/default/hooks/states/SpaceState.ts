import { z } from 'zod';
import { buildUseState, type StateDefinition } from '@/lib/arkitekt/state';

// --- Sub-Schemas ---
export const AxisSchema = z
  .object({
    __identifier: z.literal('@newswitch/axis').default('@newswitch/axis'),
    name: z.string(),
    type: z.string(),
    unit: z.string(),
  })
  .brand('@newswitch/axis')
  .describe(
    "One axis of a coordinate system: its name, what it is (mikro's AxisType), and its unit.",
  );
export type Axis = z.input<typeof AxisSchema>;
export type AxisOutput = z.infer<typeof AxisSchema>;

export const CoordinateSystemSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/coordinate_system')
      .default('@newswitch/coordinate_system'),
    name: z.string(),
    axes: z.array(
      AxisSchema.describe(
        "One axis of a coordinate system: its name, what it is (mikro's AxisType), and its unit.",
      ),
    ),
  })
  .brand('@newswitch/coordinate_system')
  .describe(
    'A node of the graph: a frame, by name, and the axes a position in it has.',
  );
export type CoordinateSystem = z.input<typeof CoordinateSystemSchema>;
export type CoordinateSystemOutput = z.infer<typeof CoordinateSystemSchema>;

export const DimensionPartSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/dimension_part')
      .default('@newswitch/dimension_part'),
    kind: z.string(),
    input_axes: z.array(z.string()),
    output_axes: z.array(z.string()),
    scale: z.array(z.number()).nullable().optional(),
    translation: z.array(z.number()).nullable().optional(),
    affine: z.array(z.array(z.number())).nullable().optional(),
  })
  .brand('@newswitch/dimension_part')
  .describe(
    'One part of a BY_DIMENSION: its own input axes onto its own output axes, by one kind.',
  );
export type DimensionPart = z.input<typeof DimensionPartSchema>;
export type DimensionPartOutput = z.infer<typeof DimensionPartSchema>;

export const TransformationSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/transformation')
      .default('@newswitch/transformation'),
    input: z.string(),
    output: z.string(),
    kind: z.string(),
    name: z.string(),
    scale: z.array(z.number()).nullable().optional(),
    translation: z.array(z.number()).nullable().optional(),
    affine: z.array(z.array(z.number())).nullable().optional(),
    parts: z.array(
      DimensionPartSchema.describe(
        'One part of a BY_DIMENSION: its own input axes onto its own output axes, by one kind.',
      ),
    ),
  })
  .brand('@newswitch/transformation')
  .describe(
    "An edge of the graph, from `input` to `output`, of one of mikro's kinds.",
  );
export type Transformation = z.input<typeof TransformationSchema>;
export type TransformationOutput = z.infer<typeof TransformationSchema>;

export const WellShapeSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/well_shape')
      .default('@newswitch/well_shape'),
    name: z.string(),
    x: z.number(),
    y: z.number(),
    diameter_um: z.number().nullable().optional(),
    size_um: z.number().nullable().optional(),
  })
  .brand('@newswitch/well_shape')
  .describe(
    'One well of a mounted plate: its middle on the sample, and how wide it is.',
  );
export type WellShape = z.input<typeof WellShapeSchema>;
export type WellShapeOutput = z.infer<typeof WellShapeSchema>;

export const HolderShapeSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/holder_shape')
      .default('@newswitch/holder_shape'),
    name: z.string(),
    kind: z.string(),
    width_um: z.number(),
    height_um: z.number(),
    wells: z.array(
      WellShapeSchema.describe(
        'One well of a mounted plate: its middle on the sample, and how wide it is.',
      ),
    ),
  })
  .brand('@newswitch/holder_shape')
  .describe(
    'What is mounted, in sample micrometres from its top left corner: for a view to draw.',
  );
export type HolderShape = z.input<typeof HolderShapeSchema>;
export type HolderShapeOutput = z.infer<typeof HolderShapeSchema>;

export const DetectorPlacementSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/detector_placement')
      .default('@newswitch/detector_placement'),
    detector: z.string(),
    to_sample: z.array(z.array(z.number())),
    pixel_um: z.array(z.number()),
    calibrated: z.boolean(),
  })
  .brand('@newswitch/detector_placement')
  .describe(
    "Where an imaging detector's pixels are on the sample now: column, row and plane to micrometres.",
  );
export type DetectorPlacement = z.input<typeof DetectorPlacementSchema>;
export type DetectorPlacementOutput = z.infer<typeof DetectorPlacementSchema>;

export const MeasuredPointSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/measured_point')
      .default('@newswitch/measured_point'),
    detector: z.string(),
    x: z.number(),
    y: z.number(),
    z: z.number(),
  })
  .brand('@newswitch/measured_point')
  .describe(
    'Where a detector that measures at one point (a thermometer) measures, in sample micrometres.',
  );
export type MeasuredPoint = z.input<typeof MeasuredPointSchema>;
export type MeasuredPointOutput = z.infer<typeof MeasuredPointSchema>;

// --- Main Schema ---
export const SpaceStateSchema = z.object({
  systems: z.array(
    CoordinateSystemSchema.describe(
      'A node of the graph: a frame, by name, and the axes a position in it has.',
    ),
  ),
  transformations: z.array(
    TransformationSchema.describe(
      "An edge of the graph, from `input` to `output`, of one of mikro's kinds.",
    ),
  ),
  mount: z.array(z.array(z.number())),
  mount_id: z.string(),
  holder: z.string().nullable().optional(),
  holders: z.array(z.string()),
  shape: HolderShapeSchema.describe(
    'What is mounted, in sample micrometres from its top left corner: for a view to draw.',
  )
    .nullable()
    .optional(),
  detectors: z.record(
    z.string(),
    DetectorPlacementSchema.describe(
      "Where an imaging detector's pixels are on the sample now: column, row and plane to micrometres.",
    ),
  ),
  points: z.record(
    z.string(),
    MeasuredPointSchema.describe(
      'Where a detector that measures at one point (a thermometer) measures, in sample micrometres.',
    ),
  ),
});

// --- Type ---
export type SpaceState = z.infer<typeof SpaceStateSchema>;

// --- Definition ---
export const SpaceStateDefinition: StateDefinition<SpaceState, 'SpaceState'> = {
  appKey: 'default',
  key: 'SpaceState',
  schema: SpaceStateSchema,
};

/**
 * Hook to sync SpaceState
 */
export const useSpaceState = buildUseState<SpaceState>(SpaceStateDefinition);
