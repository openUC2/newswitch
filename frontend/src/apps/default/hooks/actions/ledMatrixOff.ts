import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/rekuest/task';

// --- Shared Models ---

// --- Schemas ---
export const LedMatrixOffArgsSchema = z.object({});
export const LedMatrixOffReturnSchema = z.object({});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type LedMatrixOffArgs = z.input<typeof LedMatrixOffArgsSchema>;
export type LedMatrixOffReturn = z.infer<typeof LedMatrixOffReturnSchema>;

// --- Definition ---
export const LedMatrixOffDefinition: ActionDefinition<
  LedMatrixOffArgs,
  LedMatrixOffReturn
> = {
  name: 'led_matrix_off',
  appKey: 'default',
  description: 'Turn the LED matrix off.',
  argsSchema: LedMatrixOffArgsSchema,
  returnSchema: LedMatrixOffReturnSchema,
  lockKeys: ['illumination'],
};

/**
 * Turn the LED matrix off.
 */
export const useLedMatrixOff = () => {
  return useAction(LedMatrixOffDefinition);
};
