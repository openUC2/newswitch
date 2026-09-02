import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/rekuest/task';

// --- Shared Models ---

// --- Schemas ---
export const HomeObjectiveArgsSchema = z.object({});
export const HomeObjectiveReturnSchema = z.object({});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type HomeObjectiveArgs = z.input<typeof HomeObjectiveArgsSchema>;
export type HomeObjectiveReturn = z.infer<typeof HomeObjectiveReturnSchema>;

// --- Definition ---
export const HomeObjectiveDefinition: ActionDefinition<
  HomeObjectiveArgs,
  HomeObjectiveReturn
> = {
  name: 'home_objective',
  appKey: 'default',
  description: 'Home the objective changer.',
  argsSchema: HomeObjectiveArgsSchema,
  returnSchema: HomeObjectiveReturnSchema,
  lockKeys: ['objective'],
};

/**
 * Home the objective changer.
 */
export const useHomeObjective = () => {
  return useAction(HomeObjectiveDefinition);
};
