import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---

// --- Schemas ---
export const MountHolderArgsSchema = z.object({
  /** One of the holders the description names for the sample. */
  holder: z
    .string()
    .describe('One of the holders the description names for the sample.'),
  /** Which sample, by the cube holding it; may be left out when there is one. */
  sample: z
    .string()
    .describe(
      'Which sample, by the cube holding it; may be left out when there is one.',
    )
    .nullable()
    .optional(),
});
export const MountHolderReturnSchema = z.object({});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type MountHolderArgs = z.input<typeof MountHolderArgsSchema>;
export type MountHolderReturn = z.infer<typeof MountHolderReturnSchema>;

// --- Definition ---
export const MountHolderDefinition: ActionDefinition<
  MountHolderArgs,
  MountHolderReturn
> = {
  name: 'mount_holder',
  appKey: 'default',
  description:
    "Mount another holder: a new sample, where the description says it sits.\n\nThe images taken were of what was mounted before: that sample's leave the expanse.",
  argsSchema: MountHolderArgsSchema,
  returnSchema: MountHolderReturnSchema,
  lockKeys: ['expanse_state', 'motion'],
};

/**
 * Mount another holder: a new sample, where the description says it sits.

The images taken were of what was mounted before: that sample's leave the expanse.
 */
export const useMountHolder = () => {
  return useAction(MountHolderDefinition);
};
