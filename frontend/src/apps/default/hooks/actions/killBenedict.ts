import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---

// --- Schemas ---
export const KillBenedictArgsSchema = z.object({
  kill_hard: z.string(),
  die_young: z.boolean(),
});
export const KillBenedictReturnSchema = z.object({});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type KillBenedictArgs = z.input<typeof KillBenedictArgsSchema>;
export type KillBenedictReturn = z.infer<typeof KillBenedictReturnSchema>;

// --- Definition ---
export const KillBenedictDefinition: ActionDefinition<
  KillBenedictArgs,
  KillBenedictReturn
> = {
  name: 'kill_benedict',
  appKey: 'default',
  description:
    'Move the stage to a specified position with a long execution time to test optimistic updates.',
  argsSchema: KillBenedictArgsSchema,
  returnSchema: KillBenedictReturnSchema,
  lockKeys: ['stage_position'],
};

/**
 * Move the stage to a specified position with a long execution time to test optimistic updates.
 */
export const useKillBenedict = () => {
  return useAction(KillBenedictDefinition);
};
