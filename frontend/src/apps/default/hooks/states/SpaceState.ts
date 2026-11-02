import { z } from 'zod';
import { buildUseState, type StateDefinition } from '@/lib/arkitekt/state';

// --- Sub-Schemas ---
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
    "Where a detector's pixels are on the sample now: column, row and plane to micrometres.",
  );
export type DetectorPlacement = z.input<typeof DetectorPlacementSchema>;
export type DetectorPlacementOutput = z.infer<typeof DetectorPlacementSchema>;

// --- Main Schema ---
export const SpaceStateSchema = z.object({
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
      "Where a detector's pixels are on the sample now: column, row and plane to micrometres.",
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
