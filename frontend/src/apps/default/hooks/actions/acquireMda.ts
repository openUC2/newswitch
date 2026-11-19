import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---
export const AcquiredDatasetSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/acquired_dataset')
      .default('@newswitch/acquired_dataset'),
    id: z.string(),
    name: z.string(),
    /** Which position of the acquisition it holds, from 0 */
    position: z
      .number()
      .describe('Which position of the acquisition it holds, from 0'),
    /** Which detector's record it is */
    detector: z.string().describe("Which detector's record it is"),
  })
  .brand('@newswitch/acquired_dataset')
  .describe('A dataset an acquisition created, in the store it went to.');
export type AcquiredDataset = z.input<typeof AcquiredDatasetSchema>;
export type AcquiredDatasetOutput = z.infer<typeof AcquiredDatasetSchema>;

// --- Schemas ---
export const AcquireMdaArgsSchema = z.object({
  /** The channels to image, by the names the optics give them; all of one sample. */
  channels: z
    .array(z.string())
    .describe(
      'The channels to image, by the names the optics give them; all of one sample.',
    ),
  /** How deep the stack is, in micrometres; 0: one plane, where the focus is. */
  z_range_um: z
    .number()
    .describe(
      'How deep the stack is, in micrometres; 0: one plane, where the focus is.',
    )
    .nullable()
    .optional(),
  /** How far apart its planes are, in micrometres. */
  z_step_um: z
    .number()
    .describe('How far apart its planes are, in micrometres.')
    .nullable()
    .optional(),
  /** How many tiles across. */
  columns: z.number().describe('How many tiles across.').nullable().optional(),
  /** How many tiles down. */
  rows: z.number().describe('How many tiles down.').nullable().optional(),
  /** How much neighbouring tiles share, from 0 to 0.9. */
  overlap: z
    .number()
    .describe('How much neighbouring tiles share, from 0 to 0.9.')
    .nullable()
    .optional(),
  /** How many times to take all of it. */
  times: z
    .number()
    .describe('How many times to take all of it.')
    .nullable()
    .optional(),
  /** Seconds from the start of one time to the next; 0: right after it. */
  every_s: z
    .number()
    .describe(
      'Seconds from the start of one time to the next; 0: right after it.',
    )
    .nullable()
    .optional(),
  /** What to call the datasets; each tile's gets its tile's name too. */
  name: z
    .string()
    .describe(
      "What to call the datasets; each tile's gets its tile's name too.",
    )
    .nullable()
    .optional(),
});
export const AcquireMdaReturnSchema = z.object({
  /** The datasets created: for each tile, one per detector. */
  datasets: z.array(
    AcquiredDatasetSchema.describe(
      'A dataset an acquisition created, in the store it went to.',
    ),
  ),
});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type AcquireMdaArgs = z.input<typeof AcquireMdaArgsSchema>;
export type AcquireMdaReturn = z.infer<typeof AcquireMdaReturnSchema>;

// --- Definition ---
export const AcquireMdaDefinition: ActionDefinition<
  AcquireMdaArgs,
  AcquireMdaReturn
> = {
  name: 'acquire_mda',
  appKey: 'default',
  description:
    'Acquire the channels named, on a stack of planes, over a grid of tiles, some times.\n\nEach channel is taken at the brightness its source has now (its preset when it is off) and the\nexposure its detectors have now. The planes are centred where the focus is, and the tiles of a\ngrid around where the view is, a field of view apart less the overlap.',
  argsSchema: AcquireMdaArgsSchema,
  returnSchema: AcquireMdaReturnSchema,
  lockKeys: ['detector', 'motion', 'swap', 'tune'],
};

/**
 * Acquire the channels named, on a stack of planes, over a grid of tiles, some times.

Each channel is taken at the brightness its source has now (its preset when it is off) and the
exposure its detectors have now. The planes are centred where the focus is, and the tiles of a
grid around where the view is, a field of view apart less the overlap.
 */
export const useAcquireMda = () => {
  return useAction(AcquireMdaDefinition);
};
