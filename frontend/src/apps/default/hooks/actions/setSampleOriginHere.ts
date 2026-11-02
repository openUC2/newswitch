import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---

// --- Schemas ---
export const SetSampleOriginHereArgsSchema = z.object({
  /** Whose image's middle; by default the first that is on. */
  detector: z
    .string()
    .describe("Whose image's middle; by default the first that is on.")
    .nullable()
    .optional(),
});
export const SetSampleOriginHereReturnSchema = z.object({});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type SetSampleOriginHereArgs = z.input<
  typeof SetSampleOriginHereArgsSchema
>;
export type SetSampleOriginHereReturn = z.infer<
  typeof SetSampleOriginHereReturnSchema
>;

// --- Definition ---
export const SetSampleOriginHereDefinition: ActionDefinition<
  SetSampleOriginHereArgs,
  SetSampleOriginHereReturn
> = {
  name: 'set_sample_origin_here',
  appKey: 'default',
  description: "Make where a detector looks now the sample's x and y 0.",
  argsSchema: SetSampleOriginHereArgsSchema,
  returnSchema: SetSampleOriginHereReturnSchema,
  lockKeys: [],
};

/**
 * Make where a detector looks now the sample's x and y 0.
 */
export const useSetSampleOriginHere = () => {
  return useAction(SetSampleOriginHereDefinition);
};
