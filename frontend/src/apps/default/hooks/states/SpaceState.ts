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

export const PlaceShapeSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/place_shape')
      .default('@newswitch/place_shape'),
    grid: z.string(),
    name: z.string(),
    x: z.number(),
    y: z.number(),
    diameter_um: z.number().nullable().optional(),
    size_um: z.number().nullable().optional(),
  })
  .brand('@newswitch/place_shape')
  .describe(
    'One place of a grid of what is mounted (a well, an electrode): its middle on the sample, and\n    how wide it is.',
  );
export type PlaceShape = z.input<typeof PlaceShapeSchema>;
export type PlaceShapeOutput = z.infer<typeof PlaceShapeSchema>;

export const HolderShapeSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/holder_shape')
      .default('@newswitch/holder_shape'),
    name: z.string(),
    kind: z.string(),
    width_um: z.number(),
    height_um: z.number(),
    places: z.array(
      PlaceShapeSchema.describe(
        'One place of a grid of what is mounted (a well, an electrode): its middle on the sample, and\n    how wide it is.',
      ),
    ),
  })
  .brand('@newswitch/holder_shape')
  .describe(
    'What is mounted, in sample micrometres from its top left corner: for a view to draw.',
  );
export type HolderShape = z.input<typeof HolderShapeSchema>;
export type HolderShapeOutput = z.infer<typeof HolderShapeSchema>;

export const SampleSpaceSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/sample_space')
      .default('@newswitch/sample_space'),
    sample: z.string(),
    mount: z.array(z.array(z.number())),
    mount_id: z.string(),
    mounted_at: z.string(),
    holder: z.string().nullable().optional(),
    holders: z.array(z.string()),
    /** What is mounted, in sample micrometres from its top left corner: for a view to draw. */
    shape: HolderShapeSchema.describe(
      'What is mounted, in sample micrometres from its top left corner: for a view to draw.',
    )
      .nullable()
      .optional(),
  })
  .brand('@newswitch/sample_space')
  .describe(
    'One sample, on a stage of its own: where what it is mounted on sits, and what that is.',
  );
export type SampleSpace = z.input<typeof SampleSpaceSchema>;
export type SampleSpaceOutput = z.infer<typeof SampleSpaceSchema>;

export const DetectorPlacementSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/detector_placement')
      .default('@newswitch/detector_placement'),
    detector: z.string(),
    to_sample: z.array(z.array(z.number())),
    pixel_um: z.array(z.number()),
    calibrated: z.boolean(),
    sample: z.string(),
  })
  .brand('@newswitch/detector_placement')
  .describe(
    "Where an imaging detector's pixels are on its sample now: column, row and plane to micrometres.",
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
    sample: z.string(),
  })
  .brand('@newswitch/measured_point')
  .describe(
    "Where a detector that measures at one point (a thermometer) measures, in its sample's\n    micrometres.",
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
  samples: z.record(
    z.string(),
    SampleSpaceSchema.describe(
      'One sample, on a stage of its own: where what it is mounted on sits, and what that is.',
    ),
  ),
  detectors: z.record(
    z.string(),
    DetectorPlacementSchema.describe(
      "Where an imaging detector's pixels are on its sample now: column, row and plane to micrometres.",
    ),
  ),
  points: z.record(
    z.string(),
    MeasuredPointSchema.describe(
      "Where a detector that measures at one point (a thermometer) measures, in its sample's\n    micrometres.",
    ),
  ),
});

// --- Type ---
export type SpaceState = z.infer<typeof SpaceStateSchema>;

// --- Definition ---
export const SpaceStateDefinition: StateDefinition<SpaceState, 'space'> = {
  appKey: 'default',
  key: 'space',
  schema: SpaceStateSchema,
};

/**
 * Hook to sync space
 */
export const useSpaceState = buildUseState<SpaceState>(SpaceStateDefinition);
