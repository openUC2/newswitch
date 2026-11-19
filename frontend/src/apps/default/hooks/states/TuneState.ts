import { z } from 'zod';
import { buildUseState, type StateDefinition } from '@/lib/arkitekt/state';

// --- Sub-Schemas ---
export const TuneValueSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/tune_value')
      .default('@newswitch/tune_value'),
    name: z.string(),
    current: z.number(),
    unit: z.string(),
    minimum: z.number().nullable().optional(),
    maximum: z.number().nullable().optional(),
    step: z.number().nullable().optional(),
    does: z.array(z.string()),
  })
  .brand('@newswitch/tune_value')
  .describe('A value of an element, and what tuning it does.');
export type TuneValue = z.input<typeof TuneValueSchema>;
export type TuneValueOutput = z.infer<typeof TuneValueSchema>;

// --- Main Schema ---
export const TuneStateSchema = z.object({
  tunes: z.record(
    z.string(),
    z.record(
      z.string(),
      TuneValueSchema.describe(
        'A value of an element, and what tuning it does.',
      ),
    ),
  ),
});

// --- Type ---
export type TuneState = z.infer<typeof TuneStateSchema>;

// --- Definition ---
export const TuneStateDefinition: StateDefinition<TuneState, 'TuneState'> = {
  appKey: 'default',
  key: 'TuneState',
  schema: TuneStateSchema,
};

/**
 * Hook to sync TuneState
 */
export const useTuneState = buildUseState<TuneState>(TuneStateDefinition);
