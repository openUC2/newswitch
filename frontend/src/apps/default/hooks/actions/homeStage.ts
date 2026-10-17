import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/rekuest/task';

// --- Shared Models ---

// --- Schemas ---
export const HomeStageArgsSchema = z.object({
  /** Axes to home (subset of X/Y/Z/A). Default: Z, X, Y. */
  axes: z
    .array(z.string())
    .describe('Axes to home (subset of X/Y/Z/A). Default: Z, X, Y.')
    .nullable()
    .optional(),
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
    'Home stage axes sequentially in a mechanically safe order (Z first).',
  argsSchema: HomeStageArgsSchema,
  returnSchema: HomeStageReturnSchema,
  lockKeys: ['stage_position'],
};

/**
 * Home stage axes sequentially in a mechanically safe order (Z first).
 */
export const useHomeStage = () => {
  return useAction(HomeStageDefinition);
};
