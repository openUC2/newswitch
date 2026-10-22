import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---

// --- Schemas ---
export const TurnOffIlluminationChannelArgsSchema = z.object({
  /** Illumination channel number to turn off */
  channel: z.number().describe('Illumination channel number to turn off'),
});
export const TurnOffIlluminationChannelReturnSchema = z.object({
  /** Confirmation message. */
  return0: z.string().describe('Confirmation message.'),
});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type TurnOffIlluminationChannelArgs = z.input<
  typeof TurnOffIlluminationChannelArgsSchema
>;
export type TurnOffIlluminationChannelReturn = z.infer<
  typeof TurnOffIlluminationChannelReturnSchema
>;

// --- Definition ---
export const TurnOffIlluminationChannelDefinition: ActionDefinition<
  TurnOffIlluminationChannelArgs,
  TurnOffIlluminationChannelReturn
> = {
  name: 'turn_off_illumination_channel',
  appKey: 'default',
  description: 'Turn off a specific illumination channel.',
  argsSchema: TurnOffIlluminationChannelArgsSchema,
  returnSchema: TurnOffIlluminationChannelReturnSchema,
  lockKeys: ['illumination'],
};

/**
 * Turn off a specific illumination channel.
 */
export const useTurnOffIlluminationChannel = () => {
  return useAction(TurnOffIlluminationChannelDefinition);
};
