import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---

// --- Schemas ---
export const MoveArgsSchema = z.object({
  /** How far, by variable: ``{"stage.x": 10.0, "stage.y": -5.0}``. */
  targets: z
    .record(z.string(), z.number())
    .describe('How far, by variable: ``{"stage.x": 10.0, "stage.y": -5.0}``.'),
  /** By them, rather than to them. */
  relative: z
    .boolean()
    .describe('By them, rather than to them.')
    .nullable()
    .optional(),
});
export const MoveReturnSchema = z.object({});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type MoveArgs = z.input<typeof MoveArgsSchema>;
export type MoveReturn = z.infer<typeof MoveReturnSchema>;

// --- Definition ---
export const MoveDefinition: ActionDefinition<MoveArgs, MoveReturn> = {
  name: 'move',
  appKey: 'default',
  description: 'Move variables together: to those values, or by them.',
  argsSchema: MoveArgsSchema,
  returnSchema: MoveReturnSchema,
  lockKeys: ['motion'],
};

/**
 * Move variables together: to those values, or by them.
 */
export const useMove = () => {
  return useAction(MoveDefinition);
};
