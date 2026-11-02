import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---

// --- Schemas ---
export const RunAutofocusArgsSchema = z.object({
  /** Total sweep range in micrometers, centered on the current Z. By default, from
how deep the detector's objective sees sharply. */
  z_range: z
    .number()
    .describe(
      "Total sweep range in micrometers, centered on the current Z. By default, from\nhow deep the detector's objective sees sharply.",
    )
    .nullable()
    .optional(),
  /** Number of Z planes to score (>= 3). */
  steps: z
    .number()
    .describe('Number of Z planes to score (>= 3).')
    .nullable()
    .optional(),
  /** The detector to read frames from; by default, the first camera that is on,
when the cameras that are on see one sample. */
  detector_name: z
    .string()
    .describe(
      'The detector to read frames from; by default, the first camera that is on,\nwhen the cameras that are on see one sample.',
    )
    .nullable()
    .optional(),
  /** What to focus with, if several things do. */
  focus: z
    .string()
    .describe('What to focus with, if several things do.')
    .nullable()
    .optional(),
  /** "laplacian_variance" (default) or "intensity_variance". */
  metric: z
    .string()
    .describe('"laplacian_variance" (default) or "intensity_variance".')
    .nullable()
    .optional(),
});
export const RunAutofocusReturnSchema = z.object({
  /** The Z position (micrometers) of best focus; the stage is left there. */
  return0: z
    .number()
    .describe(
      'The Z position (micrometers) of best focus; the stage is left there.',
    ),
});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type RunAutofocusArgs = z.input<typeof RunAutofocusArgsSchema>;
export type RunAutofocusReturn = z.infer<typeof RunAutofocusReturnSchema>;

// --- Definition ---
export const RunAutofocusDefinition: ActionDefinition<
  RunAutofocusArgs,
  RunAutofocusReturn
> = {
  name: 'run_autofocus',
  appKey: 'default',
  description:
    'Autofocus: sweep Z around the current position and move to the sharpest plane.',
  argsSchema: RunAutofocusArgsSchema,
  returnSchema: RunAutofocusReturnSchema,
  lockKeys: ['detector', 'motion'],
};

/**
 * Autofocus: sweep Z around the current position and move to the sharpest plane.
 */
export const useRunAutofocus = () => {
  return useAction(RunAutofocusDefinition);
};
