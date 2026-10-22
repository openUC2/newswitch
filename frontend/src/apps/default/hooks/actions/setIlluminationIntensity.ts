import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---

// --- Schemas ---
export const SetIlluminationIntensityArgsSchema = z.object({
  /** Light intensity value */
  intensity: z.number().describe('Light intensity value'),
  /** Illumination channel number (default 1) */
  channel: z
    .number()
    .describe('Illumination channel number (default 1)')
    .nullable()
    .optional(),
});
export const SetIlluminationIntensityReturnSchema = z.object({
  /** The actual clamped intensity value. */
  return0: z.number().describe('The actual clamped intensity value.'),
});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type SetIlluminationIntensityArgs = z.input<
  typeof SetIlluminationIntensityArgsSchema
>;
export type SetIlluminationIntensityReturn = z.infer<
  typeof SetIlluminationIntensityReturnSchema
>;

// --- Definition ---
export const SetIlluminationIntensityDefinition: ActionDefinition<
  SetIlluminationIntensityArgs,
  SetIlluminationIntensityReturn
> = {
  name: 'set_illumination_intensity',
  appKey: 'default',
  description: 'Set illumination intensity for a specific channel.',
  argsSchema: SetIlluminationIntensityArgsSchema,
  returnSchema: SetIlluminationIntensityReturnSchema,
  lockKeys: ['illumination'],
};

/**
 * Set illumination intensity for a specific channel.
 */
export const useSetIlluminationIntensity = () => {
  return useAction(SetIlluminationIntensityDefinition);
};
