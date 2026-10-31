import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---

// --- Schemas ---
export const DeactivateDetectorArgsSchema = z.object({
  /** The detector. */
  name: z.string().describe('The detector.'),
});
export const DeactivateDetectorReturnSchema = z.object({
  return0: z.string(),
});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type DeactivateDetectorArgs = z.input<
  typeof DeactivateDetectorArgsSchema
>;
export type DeactivateDetectorReturn = z.infer<
  typeof DeactivateDetectorReturnSchema
>;

// --- Definition ---
export const DeactivateDetectorDefinition: ActionDefinition<
  DeactivateDetectorArgs,
  DeactivateDetectorReturn
> = {
  name: 'deactivate_detector',
  appKey: 'default',
  description: 'Turn a detector off.',
  argsSchema: DeactivateDetectorArgsSchema,
  returnSchema: DeactivateDetectorReturnSchema,
  lockKeys: ['detector'],
};

/**
 * Turn a detector off.
 */
export const useDeactivateDetector = () => {
  return useAction(DeactivateDetectorDefinition);
};
