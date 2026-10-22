import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---

// --- Schemas ---
export const MoveToStagePositionArgsSchema = z.object({
  position_x: z.number(),
  position_y: z.number(),
  position_z: z.number(),
});
export const MoveToStagePositionReturnSchema = z.object({});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type MoveToStagePositionArgs = z.input<
  typeof MoveToStagePositionArgsSchema
>;
export type MoveToStagePositionReturn = z.infer<
  typeof MoveToStagePositionReturnSchema
>;

// --- Definition ---
export const MoveToStagePositionDefinition: ActionDefinition<
  MoveToStagePositionArgs,
  MoveToStagePositionReturn
> = {
  name: 'move_to_stage_position',
  appKey: 'default',
  description: 'Move the stage to a specified position.',
  argsSchema: MoveToStagePositionArgsSchema,
  returnSchema: MoveToStagePositionReturnSchema,
  lockKeys: ['stage_position'],
};

/**
 * Move the stage to a specified position.
 */
export const useMoveToStagePosition = () => {
  return useAction(MoveToStagePositionDefinition);
};
