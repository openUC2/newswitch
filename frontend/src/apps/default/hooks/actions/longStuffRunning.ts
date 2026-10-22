import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---

// --- Schemas ---
export const LongStuffRunningArgsSchema = z.object({});
export const LongStuffRunningReturnSchema = z.object({});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type LongStuffRunningArgs = z.input<typeof LongStuffRunningArgsSchema>;
export type LongStuffRunningReturn = z.infer<
  typeof LongStuffRunningReturnSchema
>;

// --- Definition ---
export const LongStuffRunningDefinition: ActionDefinition<
  LongStuffRunningArgs,
  LongStuffRunningReturn
> = {
  name: 'long_stuff_running',
  appKey: 'default',
  description:
    'A long-running function to test optimistic updates and progress.',
  argsSchema: LongStuffRunningArgsSchema,
  returnSchema: LongStuffRunningReturnSchema,
  lockKeys: [],
};

/**
 * A long-running function to test optimistic updates and progress.
 */
export const useLongStuffRunning = () => {
  return useAction(LongStuffRunningDefinition);
};
