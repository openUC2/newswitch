import { z } from 'zod';
import { buildUseState, type StateDefinition } from '@/lib/arkitekt/state';

// --- Sub-Schemas ---
export const SwapOptionSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/swap_option')
      .default('@newswitch/swap_option'),
    slot: z.number(),
    label: z.string(),
    kind: z.string(),
    facts: z.record(z.string(), z.string()),
  })
  .brand('@newswitch/swap_option')
  .describe('One thing a swap can put in place.');
export type SwapOption = z.input<typeof SwapOptionSchema>;
export type SwapOptionOutput = z.infer<typeof SwapOptionSchema>;

export const SwapValueSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/swap_value')
      .default('@newswitch/swap_value'),
    name: z.string(),
    current: z.number(),
    label: z.string(),
    options: z.array(
      SwapOptionSchema.describe('One thing a swap can put in place.'),
    ),
    does: z.array(z.string()),
  })
  .brand('@newswitch/swap_value')
  .describe('Which of several things is in place, and what swapping it does.');
export type SwapValue = z.input<typeof SwapValueSchema>;
export type SwapValueOutput = z.infer<typeof SwapValueSchema>;

// --- Main Schema ---
export const SwapStateSchema = z.object({
  swaps: z.record(
    z.string(),
    z.record(
      z.string(),
      SwapValueSchema.describe(
        'Which of several things is in place, and what swapping it does.',
      ),
    ),
  ),
  names: z.array(z.string()),
  homes: z.array(z.string()),
});

// --- Type ---
export type SwapState = z.infer<typeof SwapStateSchema>;

// --- Definition ---
export const SwapStateDefinition: StateDefinition<SwapState, 'swap'> = {
  appKey: 'default',
  key: 'swap',
  schema: SwapStateSchema,
};

/**
 * Hook to sync swap
 */
export const useSwapState = buildUseState<SwapState>(SwapStateDefinition);
