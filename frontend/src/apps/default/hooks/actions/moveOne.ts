import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---

// --- Schemas ---
export const MoveOneArgsSchema = z.object({
  /** The variable: ``stage.z``. */
  name: z.string().describe('The variable: ``stage.z``.'),
  /** Where to. */
  to: z.number().describe('Where to.').nullable().optional(),
  /** How far. */
  by: z.number().describe('How far.').nullable().optional(),
});
export const MoveOneReturnSchema = z.object({});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type MoveOneArgs = z.input<typeof MoveOneArgsSchema>;
export type MoveOneReturn = z.infer<typeof MoveOneReturnSchema>;

// --- Definition ---
export const MoveOneDefinition: ActionDefinition<MoveOneArgs, MoveOneReturn> = {
  name: 'move_one',
  appKey: 'default',
  description: 'Move one variable: to a value, or by one.',
  argsSchema: MoveOneArgsSchema,
  returnSchema: MoveOneReturnSchema,
  lockKeys: ['motion'],
};

/**
 * Move one variable: to a value, or by one.
 */
export const useMoveOne = () => {
  return useAction(MoveOneDefinition);
};
