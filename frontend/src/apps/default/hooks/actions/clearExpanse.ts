import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---

// --- Schemas ---
export const ClearExpanseArgsSchema = z.object({});
export const ClearExpanseReturnSchema = z.object({});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type ClearExpanseArgs = z.input<typeof ClearExpanseArgsSchema>;
export type ClearExpanseReturn = z.infer<typeof ClearExpanseReturnSchema>;

// --- Definition ---
export const ClearExpanseDefinition: ActionDefinition<
  ClearExpanseArgs,
  ClearExpanseReturn
> = {
  name: 'clear_expanse',
  appKey: 'default',
  description: 'Clear the expanse state, removing all current images.',
  argsSchema: ClearExpanseArgsSchema,
  returnSchema: ClearExpanseReturnSchema,
  lockKeys: ['expanse_state'],
};

/**
 * Clear the expanse state, removing all current images.
 */
export const useClearExpanse = () => {
  return useAction(ClearExpanseDefinition);
};
