import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/rekuest/task';

// --- Shared Models ---

// --- Schemas ---
export const LedMatrixFillArgsSchema = z.object({
  r: z.number().nullable().optional(),
  g: z.number().nullable().optional(),
  b: z.number().nullable().optional(),
});
export const LedMatrixFillReturnSchema = z.object({});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type LedMatrixFillArgs = z.input<typeof LedMatrixFillArgsSchema>;
export type LedMatrixFillReturn = z.infer<typeof LedMatrixFillReturnSchema>;

// --- Definition ---
export const LedMatrixFillDefinition: ActionDefinition<
  LedMatrixFillArgs,
  LedMatrixFillReturn
> = {
  name: 'led_matrix_fill',
  appKey: 'default',
  description: 'Fill the LED matrix with a uniform colour (0-255 per channel).',
  argsSchema: LedMatrixFillArgsSchema,
  returnSchema: LedMatrixFillReturnSchema,
  lockKeys: ['illumination'],
};

/**
 * Fill the LED matrix with a uniform colour (0-255 per channel).
 */
export const useLedMatrixFill = () => {
  return useAction(LedMatrixFillDefinition);
};
