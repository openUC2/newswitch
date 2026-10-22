import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---

// --- Schemas ---
export const NeverEndingFunctionArgsSchema = z.object({});
export const NeverEndingFunctionReturnSchema = z.object({});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type NeverEndingFunctionArgs = z.input<
  typeof NeverEndingFunctionArgsSchema
>;
export type NeverEndingFunctionReturn = z.infer<
  typeof NeverEndingFunctionReturnSchema
>;

// --- Definition ---
export const NeverEndingFunctionDefinition: ActionDefinition<
  NeverEndingFunctionArgs,
  NeverEndingFunctionReturn
> = {
  name: 'never_ending_function',
  appKey: 'default',
  description:
    'A function that never ends to test how the system handles long-running functions.',
  argsSchema: NeverEndingFunctionArgsSchema,
  returnSchema: NeverEndingFunctionReturnSchema,
  lockKeys: [],
};

/**
 * A function that never ends to test how the system handles long-running functions.
 */
export const useNeverEndingFunction = () => {
  return useAction(NeverEndingFunctionDefinition);
};
