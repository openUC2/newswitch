import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---

// --- Schemas ---
export const ToggleObjectiveArgsSchema = z.object({});
export const ToggleObjectiveReturnSchema = z.object({});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type ToggleObjectiveArgs = z.input<typeof ToggleObjectiveArgsSchema>;
export type ToggleObjectiveReturn = z.infer<typeof ToggleObjectiveReturnSchema>;

// --- Definition ---
export const ToggleObjectiveDefinition: ActionDefinition<
  ToggleObjectiveArgs,
  ToggleObjectiveReturn
> = {
  name: 'toggle_objective',
  appKey: 'default',
  description: 'Toggle to the next objective in the turret.',
  argsSchema: ToggleObjectiveArgsSchema,
  returnSchema: ToggleObjectiveReturnSchema,
  lockKeys: ['objective'],
};

/**
 * Toggle to the next objective in the turret.
 */
export const useToggleObjective = () => {
  return useAction(ToggleObjectiveDefinition);
};
