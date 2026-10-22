import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---

// --- Schemas ---
export const MoveHomeArgsSchema = z.object({});
export const MoveHomeReturnSchema = z.object({});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type MoveHomeArgs = z.input<typeof MoveHomeArgsSchema>;
export type MoveHomeReturn = z.infer<typeof MoveHomeReturnSchema>;

// --- Definition ---
export const MoveHomeDefinition: ActionDefinition<
  MoveHomeArgs,
  MoveHomeReturn
> = {
  name: 'move_home',
  appKey: 'default',
  description: 'Move stage to home position.',
  argsSchema: MoveHomeArgsSchema,
  returnSchema: MoveHomeReturnSchema,
  lockKeys: ['stage_position'],
};

/**
 * Move stage to home position.
 */
export const useMoveHome = () => {
  return useAction(MoveHomeDefinition);
};
