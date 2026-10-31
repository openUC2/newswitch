import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---

// --- Schemas ---
export const TuneArgsSchema = z.object({
  /** The variable: ``laser_488.power``. */
  name: z.string().describe('The variable: ``laser_488.power``.'),
  /** To what, in its unit. */
  to: z.number().describe('To what, in its unit.'),
});
export const TuneReturnSchema = z.object({});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type TuneArgs = z.input<typeof TuneArgsSchema>;
export type TuneReturn = z.infer<typeof TuneReturnSchema>;

// --- Definition ---
export const TuneDefinition: ActionDefinition<TuneArgs, TuneReturn> = {
  name: 'tune',
  appKey: 'default',
  description: 'Change a value of an element.',
  argsSchema: TuneArgsSchema,
  returnSchema: TuneReturnSchema,
  lockKeys: ['tune'],
};

/**
 * Change a value of an element.
 */
export const useTune = () => {
  return useAction(TuneDefinition);
};
