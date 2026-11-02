import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---
export const AxisWindowSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/axis_window')
      .default('@newswitch/axis_window'),
    axis: z.string(),
    start: z.number(),
    size: z.number(),
  })
  .brand('@newswitch/axis_window')
  .describe(
    'The part of one axis a detector reads out: from `start`, `size` unbinned steps.',
  );
export type AxisWindow = z.input<typeof AxisWindowSchema>;
export type AxisWindowOutput = z.infer<typeof AxisWindowSchema>;

// --- Schemas ---
export const SetWindowArgsSchema = z.object({
  /** The detector. */
  name: z.string().describe('The detector.'),
  /** From where, and how far, on each axis, in unbinned steps; an axis none names
is read whole, so none reads everything. */
  windows: z.array(
    AxisWindowSchema.describe(
      'The part of one axis a detector reads out: from `start`, `size` unbinned steps.',
    ),
  ),
});
export const SetWindowReturnSchema = z.object({});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type SetWindowArgs = z.input<typeof SetWindowArgsSchema>;
export type SetWindowReturn = z.infer<typeof SetWindowReturnSchema>;

// --- Definition ---
export const SetWindowDefinition: ActionDefinition<
  SetWindowArgs,
  SetWindowReturn
> = {
  name: 'set_window',
  appKey: 'default',
  description:
    "Read out only a part of a detector's axes: of a camera its sensor, of a scan the field.",
  argsSchema: SetWindowArgsSchema,
  returnSchema: SetWindowReturnSchema,
  lockKeys: ['detector'],
};

/**
 * Read out only a part of a detector's axes: of a camera its sensor, of a scan the field.
 */
export const useSetWindow = () => {
  return useAction(SetWindowDefinition);
};
