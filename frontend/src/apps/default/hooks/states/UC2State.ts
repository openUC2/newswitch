import { z } from 'zod';
import { buildUseState, type StateDefinition } from '@/lib/rekuest/state';

// --- Sub-Schemas ---

// --- Main Schema ---
export const UC2StateSchema = z.object({
  connected: z.boolean(),
  transport: z.string(),
  firmware: z.string(),
  estop_active: z.boolean(),
  nodes_online: z.array(z.number()),
  last_error: z.string(),
});

// --- Type ---
export type UC2State = z.infer<typeof UC2StateSchema>;

// --- Definition ---
export const UC2StateDefinition: StateDefinition<UC2State, 'UC2State'> = {
  appKey: 'default',
  key: 'UC2State',
  schema: UC2StateSchema,
};

/**
 * Hook to sync UC2State
 */
export const useUC2State = buildUseState<UC2State>(UC2StateDefinition);
