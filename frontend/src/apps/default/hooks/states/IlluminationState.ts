import { z } from 'zod';
import { buildUseState, type StateDefinition } from '@/lib/arkitekt/state';

// --- Sub-Schemas ---
export const IlluminationSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/illumination')
      .default('@newswitch/illumination'),
    /** Enumeration of illumination source kinds. */
    kind: z.union([
      z.literal('LED').describe('Enumeration of illumination source kinds.'),
      z.literal('LASER').describe('Enumeration of illumination source kinds.'),
      z
        .literal('HALOGEN')
        .describe('Enumeration of illumination source kinds.'),
    ]),
    slot: z.number(),
    intensity: z.number(),
    wavelength: z.number(),
    fartface: z.number(),
    channel: z.number(),
    max_intensity: z.number(),
    min_intensity: z.number(),
    is_active: z.boolean(),
  })
  .brand('@newswitch/illumination')
  .describe(
    'Shared state for illumination parameters.\n\n    Note: intensity is divided by 1000 in the detector for actual scaling,\n    so 10000.0 gives an effective intensity of 10.0.\n    ',
  );
export type Illumination = z.input<typeof IlluminationSchema>;
export type IlluminationOutput = z.infer<typeof IlluminationSchema>;

// --- Main Schema ---
export const IlluminationStateSchema = z.object({
  illuminations: z.array(
    IlluminationSchema.describe(
      'Shared state for illumination parameters.\n\n    Note: intensity is divided by 1000 in the detector for actual scaling,\n    so 10000.0 gives an effective intensity of 10.0.\n    ',
    ),
  ),
});

// --- Type ---
export type IlluminationState = z.infer<typeof IlluminationStateSchema>;

// --- Definition ---
export const IlluminationStateDefinition: StateDefinition<
  IlluminationState,
  'IlluminationState'
> = {
  appKey: 'default',
  key: 'IlluminationState',
  schema: IlluminationStateSchema,
};

/**
 * Hook to sync IlluminationState
 */
export const useIlluminationState = buildUseState<IlluminationState>(
  IlluminationStateDefinition,
);
