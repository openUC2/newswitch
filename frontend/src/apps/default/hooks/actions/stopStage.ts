import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/rekuest/task';

// --- Shared Models ---

// --- Schemas ---
export const StopStageArgsSchema = z.object({
  axis: z.string().nullable().optional(),
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
    'Immediately stop one stage axis (or all axes when none is given).\n\nDeliberately lock-free so it works while a move holds the stage lock.',
  argsSchema: StopStageArgsSchema,
  returnSchema: StopStageReturnSchema,
  lockKeys: [],
};

/**
 * Immediately stop one stage axis (or all axes when none is given).

Deliberately lock-free so it works while a move holds the stage lock.
 */
export const useStopStage = () => {
  return useAction(StopStageDefinition);
};
