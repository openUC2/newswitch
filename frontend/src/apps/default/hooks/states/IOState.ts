import { z } from 'zod';
import { buildUseState, type StateDefinition } from '@/lib/arkitekt/state';

// --- Sub-Schemas ---

// --- Main Schema ---
export const IOStateSchema = z.object({
  last_saved_file: z.string().nullable().optional(),
});

// --- Type ---
export type IOState = z.infer<typeof IOStateSchema>;

// --- Definition ---
export const IOStateDefinition: StateDefinition<IOState, 'IOState'> = {
  appKey: 'default',
  key: 'IOState',
  schema: IOStateSchema,
};

/**
 * Hook to sync IOState
 */
export const useIOState = buildUseState<IOState>(IOStateDefinition);
