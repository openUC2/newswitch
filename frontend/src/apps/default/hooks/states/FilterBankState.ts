import { z } from 'zod';
import { buildUseState, type StateDefinition } from '@/lib/rekuest/state';

// --- Sub-Schemas ---
export const FilterSchema = z
  .object({
    __identifier: z.literal('filter').default('filter'),
    slot: z.number(),
    name: z.string(),
    center_wavelength: z.number(),
    bandwidth: z.number(),
    transmission: z.number(),
    is_active: z.boolean(),
  })
  .brand('filter')
  .describe(
    'Configuration for a single optical filter.\n\n    Attributes:\n        slot: Filter wheel slot number.\n        name: Human-readable filter name.\n        center_wavelength: Center wavelength of the filter passband (nm).\n        bandwidth: Full width at half maximum of the passband (nm).\n        transmission: Peak transmission efficiency (0.0 to 1.0).\n        is_active: Whether this filter is currently in the light path.\n    ',
  );
export type Filter = z.input<typeof FilterSchema>;
export type FilterOutput = z.infer<typeof FilterSchema>;

// --- Main Schema ---
export const FilterBankStateSchema = z.object({
  filters: z.array(
    FilterSchema.describe(
      'Configuration for a single optical filter.\n\n    Attributes:\n        slot: Filter wheel slot number.\n        name: Human-readable filter name.\n        center_wavelength: Center wavelength of the filter passband (nm).\n        bandwidth: Full width at half maximum of the passband (nm).\n        transmission: Peak transmission efficiency (0.0 to 1.0).\n        is_active: Whether this filter is currently in the light path.\n    ',
    ),
  ),
  current_slot: z.number(),
});

// --- Type ---
export type FilterBankState = z.infer<typeof FilterBankStateSchema>;

// --- Definition ---
export const FilterBankStateDefinition: StateDefinition<
  FilterBankState,
  'FilterBankState'
> = {
  appKey: 'default',
  key: 'FilterBankState',
  schema: FilterBankStateSchema,
};

/**
 * Hook to sync FilterBankState
 */
export const useFilterBankState = buildUseState<FilterBankState>(
  FilterBankStateDefinition,
);
