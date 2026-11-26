import { z } from 'zod';
import { buildUseState, type StateDefinition } from '@/lib/arkitekt/state';

// --- Sub-Schemas ---

// --- Main Schema ---
export const IoStateSchema = z.object({
  last_saved_file: z.string().nullable().optional(),
});

// --- Type ---
export type IoState = z.infer<typeof IoStateSchema>;

// --- Definition ---
export const IoStateDefinition: StateDefinition<IoState, 'io'> = {
  appKey: 'default',
  key: 'io',
  schema: IoStateSchema,
};

/**
 * Hook to sync io
 */
export const useIoState = buildUseState<IoState>(IoStateDefinition);
