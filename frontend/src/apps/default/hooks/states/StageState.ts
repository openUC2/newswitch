import { z } from 'zod';
import { buildUseState, type StateDefinition } from '@/lib/arkitekt/state';

// --- Sub-Schemas ---

// --- Main Schema ---
export const StageStateSchema = z.object({
  x: z.number(),
  y: z.number(),
  z: z.number(),
  a: z.number(),
  max_x: z.number(),
  min_x: z.number(),
  max_y: z.number(),
  min_y: z.number(),
  max_z: z.number(),
  min_z: z.number(),
  max_a: z.number(),
  min_a: z.number(),
  registered_step_sizes: z
    .array(z.number())
    .describe('List of registered step sizes for the stage.'),
});

// --- Type ---
export type StageState = z.infer<typeof StageStateSchema>;

// --- Definition ---
export const StageStateDefinition: StateDefinition<StageState, 'StageState'> = {
  appKey: 'default',
  key: 'StageState',
  schema: StageStateSchema,
};

/**
 * Hook to sync StageState
 */
export const useStageState = buildUseState<StageState>(StageStateDefinition);
