import { z } from 'zod';
import { buildUseState, type StateDefinition } from '@/lib/rekuest/state';

// --- Sub-Schemas ---

// --- Main Schema ---
export const AutofocusStateSchema = z.object({
  running: z.boolean(),
  best_z: z.number(),
  best_metric: z.number(),
  metric_name: z.string(),
  z_positions: z.array(z.number()),
  metrics: z.array(z.number()),
});

// --- Type ---
export type AutofocusState = z.infer<typeof AutofocusStateSchema>;

// --- Definition ---
export const AutofocusStateDefinition: StateDefinition<
  AutofocusState,
  'AutofocusState'
> = {
  appKey: 'default',
  key: 'AutofocusState',
  schema: AutofocusStateSchema,
};

/**
 * Hook to sync AutofocusState
 */
export const useAutofocusState = buildUseState<AutofocusState>(
  AutofocusStateDefinition,
);
