import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---
export const FilterSchema = z
  .object({
    __identifier: z.literal('@newswitch/filter').default('@newswitch/filter'),
    slot: z.number(),
    name: z.string(),
    center_wavelength: z.number(),
    bandwidth: z.number(),
    transmission: z.number(),
    is_active: z.boolean(),
  })
  .brand('@newswitch/filter')
  .describe('The newly active filter.');
export type Filter = z.input<typeof FilterSchema>;
export type FilterOutput = z.infer<typeof FilterSchema>;

// --- Schemas ---
export const ToggleFilterArgsSchema = z.object({});
export const ToggleFilterReturnSchema = z.object({
  /** The newly active filter. */
  return0: FilterSchema.describe('The newly active filter.'),
});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type ToggleFilterArgs = z.input<typeof ToggleFilterArgsSchema>;
export type ToggleFilterReturn = z.infer<typeof ToggleFilterReturnSchema>;

// --- Definition ---
export const ToggleFilterDefinition: ActionDefinition<
  ToggleFilterArgs,
  ToggleFilterReturn
> = {
  name: 'toggle_filter',
  appKey: 'default',
  description: 'Toggle to the next filter in the wheel.',
  argsSchema: ToggleFilterArgsSchema,
  returnSchema: ToggleFilterReturnSchema,
  lockKeys: ['filter_bank'],
};

/**
 * Toggle to the next filter in the wheel.
 */
export const useToggleFilter = () => {
  return useAction(ToggleFilterDefinition);
};
