import { z } from 'zod';
import { buildUseState, type StateDefinition } from '@/lib/arkitekt/state';

// --- Sub-Schemas ---
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
