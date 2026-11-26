import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---

// --- Schemas ---
export const HomeStageArgsSchema = z.object({
  /** The cube: ``stage``. */
  stage: z.string().describe('The cube: ``stage``.'),
});
export const HomeStageReturnSchema = z.object({});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type HomeStageArgs = z.input<typeof HomeStageArgsSchema>;
export type HomeStageReturn = z.infer<typeof HomeStageReturnSchema>;

// --- Definition ---
export const HomeStageDefinition: ActionDefinition<
  HomeStageArgs,
  HomeStageReturn
> = {
  name: 'home_stage',
  appKey: 'default',
  description:
    'Home what a stage moves, one after the other: along z first, then the rest.',
  argsSchema: HomeStageArgsSchema,
  returnSchema: HomeStageReturnSchema,
  lockKeys: ['motion'],
};

/**
 * Home what a stage moves, one after the other: along z first, then the rest.
 */
export const useHomeStage = () => {
  return useAction(HomeStageDefinition);
};
