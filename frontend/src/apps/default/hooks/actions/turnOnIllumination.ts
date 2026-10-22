import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---

// --- Schemas ---
export const TurnOnIlluminationArgsSchema = z.object({
  /** Illumination channel number (default 1) */
  channel: z
    .number()
    .describe('Illumination channel number (default 1)')
    .nullable()
    .optional(),
  /** Optional intensity to set. Uses current/default if not provided. */
  intensity: z
    .number()
    .describe(
      'Optional intensity to set. Uses current/default if not provided.',
    )
    .nullable()
    .optional(),
});
export const TurnOnIlluminationReturnSchema = z.object({
  /** Confirmation message. */
  return0: z.string().describe('Confirmation message.'),
});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type TurnOnIlluminationArgs = z.input<
  typeof TurnOnIlluminationArgsSchema
>;
export type TurnOnIlluminationReturn = z.infer<
  typeof TurnOnIlluminationReturnSchema
>;

// --- Definition ---
export const TurnOnIlluminationDefinition: ActionDefinition<
  TurnOnIlluminationArgs,
  TurnOnIlluminationReturn
> = {
  name: 'turn_on_illumination',
  appKey: 'default',
  description: 'Turn on a specific illumination channel.',
  argsSchema: TurnOnIlluminationArgsSchema,
  returnSchema: TurnOnIlluminationReturnSchema,
  lockKeys: ['illumination'],
};

/**
 * Turn on a specific illumination channel.
 */
export const useTurnOnIllumination = () => {
  return useAction(TurnOnIlluminationDefinition);
};
