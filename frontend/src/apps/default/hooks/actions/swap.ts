import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---

// --- Schemas ---
export const SwapArgsSchema = z.object({
  /** The variable: ``objective.slot``. */
  name: z.string().describe('The variable: ``objective.slot``.'),
  /** What to put in place. */
  slot: z.number().describe('What to put in place.'),
});
export const SwapReturnSchema = z.object({});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type SwapArgs = z.input<typeof SwapArgsSchema>;
export type SwapReturn = z.infer<typeof SwapReturnSchema>;

// --- Definition ---
export const SwapDefinition: ActionDefinition<SwapArgs, SwapReturn> = {
  name: 'swap',
  appKey: 'default',
  description: 'Put another thing in place.',
  argsSchema: SwapArgsSchema,
  returnSchema: SwapReturnSchema,
  lockKeys: ['swap'],
};

/**
 * Put another thing in place.
 */
export const useSwap = () => {
  return useAction(SwapDefinition);
};
