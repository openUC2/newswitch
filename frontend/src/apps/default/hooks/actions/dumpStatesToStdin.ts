import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---

// --- Schemas ---
export const DumpStatesToStdinArgsSchema = z.object({});
export const DumpStatesToStdinReturnSchema = z.object({});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type DumpStatesToStdinArgs = z.input<typeof DumpStatesToStdinArgsSchema>;
export type DumpStatesToStdinReturn = z.infer<
  typeof DumpStatesToStdinReturnSchema
>;

// --- Definition ---
export const DumpStatesToStdinDefinition: ActionDefinition<
  DumpStatesToStdinArgs,
  DumpStatesToStdinReturn
> = {
  name: 'dump_states_to_stdin',
  appKey: 'default',
  description:
    'Dump the current states of all managers for debugging purposes.',
  argsSchema: DumpStatesToStdinArgsSchema,
  returnSchema: DumpStatesToStdinReturnSchema,
  lockKeys: [
    'camera_parameters',
    'expanse_state',
    'filter_bank',
    'illumination',
    'objective',
    'stage_position',
  ],
};

/**
 * Dump the current states of all managers for debugging purposes.
 */
export const useDumpStatesToStdin = () => {
  return useAction(DumpStatesToStdinDefinition);
};
