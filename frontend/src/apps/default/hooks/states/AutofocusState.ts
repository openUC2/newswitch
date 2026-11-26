import { z } from 'zod';
import { buildUseState, type StateDefinition } from '@/lib/arkitekt/state';

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
  'autofocus'
> = {
  appKey: 'default',
  key: 'autofocus',
  schema: AutofocusStateSchema,
};

/**
 * Hook to sync autofocus
 */
export const useAutofocusState = buildUseState<AutofocusState>(
  AutofocusStateDefinition,
);
