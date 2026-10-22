import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---

// --- Schemas ---
export const MoveStageArgsSchema = z.object({
  /** X position (micrometers) */
  x: z.number().describe('X position (micrometers)').nullable().optional(),
  /** Y position (micrometers) */
  y: z.number().describe('Y position (micrometers)').nullable().optional(),
  /** Z position (micrometers) */
  z: z.number().describe('Z position (micrometers)').nullable().optional(),
  /** A (rotation) position */
  a: z.number().describe('A (rotation) position').nullable().optional(),
  /** If True, move to absolute position; if False, relative move */
  is_absolute: z
    .boolean()
    .describe('If True, move to absolute position; if False, relative move')
    .nullable()
    .optional(),
  /** Step size in micrometers for movement simulation (default: 1.0) */
  step_size: z
    .number()
    .describe('Step size in micrometers for movement simulation (default: 1.0)')
    .nullable()
    .optional(),
});
export const MoveStageReturnSchema = z.object({});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type MoveStageArgs = z.input<typeof MoveStageArgsSchema>;
export type MoveStageReturn = z.infer<typeof MoveStageReturnSchema>;

// --- Definition ---
export const MoveStageDefinition: ActionDefinition<
  MoveStageArgs,
  MoveStageReturn
> = {
  name: 'move_stage',
  appKey: 'default',
  description: 'Move the stage to a new position.',
  argsSchema: MoveStageArgsSchema,
  returnSchema: MoveStageReturnSchema,
  lockKeys: ['stage_position'],
};

/**
 * Move the stage to a new position.
 */
export const useMoveStage = () => {
  return useAction(MoveStageDefinition);
};

/** Optimistic state hooks for move_stage */

/** Optimistic writes into StageState: each sets `path` (a JSON pointer into the state) to the
 * args at `accessor` (a JSON pointer; null: the whole args). */
export const OptimisticStageState = {
  key: 'StageState',
  writes: [
    { path: '/x', pathCall: null, accessor: '/x' },
    { path: '/y', pathCall: null, accessor: '/y' },
    { path: '/z', pathCall: null, accessor: '/z' },
    { path: '/a', pathCall: null, accessor: '/a' },
  ],
} as const;
