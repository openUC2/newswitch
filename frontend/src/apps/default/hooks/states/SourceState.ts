import { z } from 'zod';
import { buildUseState, type StateDefinition } from '@/lib/arkitekt/state';

// --- Sub-Schemas ---
export const LightSourceSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/light_source')
      .default('@newswitch/light_source'),
    name: z.string(),
    emits: z.string(),
    wavelength: z.number(),
    lines: z.array(z.number()),
    max_power: z.number(),
    power: z.number(),
    lit_power: z.number(),
    on: z.boolean(),
    power_variable: z.string().nullable().optional(),
  })
  .brand('@newswitch/light_source')
  .describe('Where light starts, and how much of it there is now.');
export type LightSource = z.input<typeof LightSourceSchema>;
export type LightSourceOutput = z.infer<typeof LightSourceSchema>;

// --- Main Schema ---
export const SourceStateSchema = z.object({
  sources: z.record(
    z.string(),
    LightSourceSchema.describe(
      'Where light starts, and how much of it there is now.',
    ),
  ),
});

// --- Type ---
export type SourceState = z.infer<typeof SourceStateSchema>;

// --- Definition ---
export const SourceStateDefinition: StateDefinition<
  SourceState,
  'SourceState'
> = {
  appKey: 'default',
  key: 'SourceState',
  schema: SourceStateSchema,
};

/**
 * Hook to sync SourceState
 */
export const useSourceState = buildUseState<SourceState>(SourceStateDefinition);
