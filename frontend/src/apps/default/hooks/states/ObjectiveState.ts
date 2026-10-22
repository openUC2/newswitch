import { z } from 'zod';
import { buildUseState, type StateDefinition } from '@/lib/arkitekt/state';

// --- Sub-Schemas ---
export const ObjectiveLensSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/objective_lens')
      .default('@newswitch/objective_lens'),
    slot: z.number(),
    name: z.string(),
    magnification: z.number(),
    numerical_aperture: z.number(),
    working_distance: z.number(),
    binning_factor: z.number(),
  })
  .brand('@newswitch/objective_lens')
  .describe('Configuration for a single objective lens.');
export type ObjectiveLens = z.input<typeof ObjectiveLensSchema>;
export type ObjectiveLensOutput = z.infer<typeof ObjectiveLensSchema>;

// --- Main Schema ---
export const ObjectiveStateSchema = z.object({
  slot: z.number(),
  magnification: z.number(),
  name: z.string(),
  mounted_lenses: z.array(
    ObjectiveLensSchema.describe('Configuration for a single objective lens.'),
  ),
});

// --- Type ---
export type ObjectiveState = z.infer<typeof ObjectiveStateSchema>;

// --- Definition ---
export const ObjectiveStateDefinition: StateDefinition<
  ObjectiveState,
  'ObjectiveState'
> = {
  appKey: 'default',
  key: 'ObjectiveState',
  schema: ObjectiveStateSchema,
};

/**
 * Hook to sync ObjectiveState
 */
export const useObjectiveState = buildUseState<ObjectiveState>(
  ObjectiveStateDefinition,
);
