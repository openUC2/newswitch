import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---
export const PositionSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/position')
      .default('@newswitch/position'),
    system: z.string(),
    coordinates: z.record(z.string(), z.number()),
  })
  .brand('@newswitch/position')
  .describe(
    'Where, by axis name: in the sample, the stage, a well (``well:B3``), an image\ntaken (``image:<id>``), a detector (``detector:<name>``, its pixels as they are now;\na thermometer, where it measures). Without z, z stays.',
  );
export type Position = z.input<typeof PositionSchema>;
export type PositionOutput = z.infer<typeof PositionSchema>;

// --- Schemas ---
export const MoveToArgsSchema = z.object({
  /** Where, by axis name: in the sample, the stage, a well (``well:B3``), an image
taken (``image:<id>``), a detector (``detector:<name>``, its pixels as they are now;
a thermometer, where it measures). Without z, z stays. */
  position: PositionSchema.describe(
    'Where, by axis name: in the sample, the stage, a well (``well:B3``), an image\ntaken (``image:<id>``), a detector (``detector:<name>``, its pixels as they are now;\na thermometer, where it measures). Without z, z stays.',
  ),
  /** Whose image; by default the first that is on. */
  detector: z
    .string()
    .describe('Whose image; by default the first that is on.')
    .nullable()
    .optional(),
});
export const MoveToReturnSchema = z.object({});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type MoveToArgs = z.input<typeof MoveToArgsSchema>;
export type MoveToReturn = z.infer<typeof MoveToReturnSchema>;

// --- Definition ---
export const MoveToDefinition: ActionDefinition<MoveToArgs, MoveToReturn> = {
  name: 'move_to',
  appKey: 'default',
  description:
    "Look at a place: the middle of the detector's image goes there.",
  argsSchema: MoveToArgsSchema,
  returnSchema: MoveToReturnSchema,
  lockKeys: ['motion'],
};

/**
 * Look at a place: the middle of the detector's image goes there.
 */
export const useMoveTo = () => {
  return useAction(MoveToDefinition);
};
