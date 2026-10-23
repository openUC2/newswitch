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
    channel: z.number(),
    max_intensity: z.number(),
    min_intensity: z.number(),
    is_active: z.boolean(),
  })
  .brand('@newswitch/illumination')
  .describe(
    'A light source: its kind, wavelength (nm), hardware channel, and intensity within\n    min..max (the light it gives is intensity / max_intensity of its full power).',
  );
export type Illumination = z.input<typeof IlluminationSchema>;
export type IlluminationOutput = z.infer<typeof IlluminationSchema>;

// --- Main Schema ---
export const IlluminationStateSchema = z.object({
  illuminations: z.array(
    IlluminationSchema.describe(
      'A light source: its kind, wavelength (nm), hardware channel, and intensity within\n    min..max (the light it gives is intensity / max_intensity of its full power).',
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
