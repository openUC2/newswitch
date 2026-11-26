import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---

// --- Schemas ---
export const StopStageArgsSchema = z.object({
  /** The cube: ``stage``. */
  stage: z.string().describe('The cube: ``stage``.'),
});
export const StopStageReturnSchema = z.object({});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type StopStageArgs = z.input<typeof StopStageArgsSchema>;
export type StopStageReturn = z.infer<typeof StopStageReturnSchema>;

// --- Definition ---
export const StopStageDefinition: ActionDefinition<
  StopStageArgs,
  StopStageReturn
> = {
  name: 'stop_stage',
  appKey: 'default',
  description:
    'Stop what a stage moves, where it is. It holds no lock, so it stops a move under way.',
  argsSchema: StopStageArgsSchema,
  returnSchema: StopStageReturnSchema,
  lockKeys: [],
};

/**
 * Stop what a stage moves, where it is. It holds no lock, so it stops a move under way.
 */
export const useStopStage = () => {
  return useAction(StopStageDefinition);
};
