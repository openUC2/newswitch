import { z } from 'zod';
import { buildUseState, type StateDefinition } from '@/lib/arkitekt/state';

// --- Sub-Schemas ---
export const MoveValueSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/move_value')
      .default('@newswitch/move_value'),
    name: z.string(),
    value: z.number(),
    unit: z.string(),
    along: z.string(),
    minimum: z.number().nullable().optional(),
    maximum: z.number().nullable().optional(),
    step: z.number().nullable().optional(),
    does: z.array(z.string()),
  })
  .brand('@newswitch/move_value')
  .describe('A value along a direction, and what moving it does.');
export type MoveValue = z.input<typeof MoveValueSchema>;
export type MoveValueOutput = z.infer<typeof MoveValueSchema>;

// --- Main Schema ---
export const MoveStateSchema = z.object({
  moves: z.record(
    z.string(),
    z.record(
      z.string(),
      MoveValueSchema.describe(
        'A value along a direction, and what moving it does.',
      ),
    ),
  ),
});

// --- Type ---
export type MoveState = z.infer<typeof MoveStateSchema>;

// --- Definition ---
export const MoveStateDefinition: StateDefinition<MoveState, 'MoveState'> = {
  appKey: 'default',
  key: 'MoveState',
  schema: MoveStateSchema,
};

/**
 * Hook to sync MoveState
 */
export const useMoveState = buildUseState<MoveState>(MoveStateDefinition);
