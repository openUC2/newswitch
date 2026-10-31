import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---

// --- Schemas ---
export const SetRegionArgsSchema = z.object({
  /** The detector. */
  name: z.string().describe('The detector.'),
  /** Where it starts, in unbinned sensor pixels. */
  x: z.number().describe('Where it starts, in unbinned sensor pixels.'),
  /** Where it starts, in unbinned sensor pixels. */
  y: z.number().describe('Where it starts, in unbinned sensor pixels.'),
  /** How wide it is. */
  width: z.number().describe('How wide it is.'),
  /** How high it is. */
  height: z.number().describe('How high it is.'),
});
export const SetRegionReturnSchema = z.object({});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type SetRegionArgs = z.input<typeof SetRegionArgsSchema>;
export type SetRegionReturn = z.infer<typeof SetRegionReturnSchema>;

// --- Definition ---
export const SetRegionDefinition: ActionDefinition<
  SetRegionArgs,
  SetRegionReturn
> = {
  name: 'set_region',
  appKey: 'default',
  description:
    "Read out only a part of a detector's sensor; a width or height of 0 is all of it.",
  argsSchema: SetRegionArgsSchema,
  returnSchema: SetRegionReturnSchema,
  lockKeys: ['detector'],
};

/**
 * Read out only a part of a detector's sensor; a width or height of 0 is all of it.
 */
export const useSetRegion = () => {
  return useAction(SetRegionDefinition);
};
