import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---

// --- Schemas ---
export const SwitchObjectiveArgsSchema = z.object({
  /** Objective slot number */
  slot: z.number().describe('Objective slot number'),
});
export const SwitchObjectiveReturnSchema = z.object({});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type SwitchObjectiveArgs = z.input<typeof SwitchObjectiveArgsSchema>;
export type SwitchObjectiveReturn = z.infer<typeof SwitchObjectiveReturnSchema>;

// --- Definition ---
export const SwitchObjectiveDefinition: ActionDefinition<
  SwitchObjectiveArgs,
  SwitchObjectiveReturn
> = {
  name: 'switch_objective',
  appKey: 'default',
  description: 'Switch to a specific objective slot.',
  argsSchema: SwitchObjectiveArgsSchema,
  returnSchema: SwitchObjectiveReturnSchema,
  lockKeys: ['objective'],
};

/**
 * Switch to a specific objective slot.
 */
export const useSwitchObjective = () => {
  return useAction(SwitchObjectiveDefinition);
};
