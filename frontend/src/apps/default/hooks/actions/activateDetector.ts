import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---

// --- Schemas ---
export const ActivateDetectorArgsSchema = z.object({
  /** The detector. */
  name: z.string().describe('The detector.'),
});
export const ActivateDetectorReturnSchema = z.object({});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type ActivateDetectorArgs = z.input<typeof ActivateDetectorArgsSchema>;
export type ActivateDetectorReturn = z.infer<
  typeof ActivateDetectorReturnSchema
>;

// --- Definition ---
export const ActivateDetectorDefinition: ActionDefinition<
  ActivateDetectorArgs,
  ActivateDetectorReturn
> = {
  name: 'activate_detector',
  appKey: 'default',
  description: 'Turn a detector on.',
  argsSchema: ActivateDetectorArgsSchema,
  returnSchema: ActivateDetectorReturnSchema,
  lockKeys: ['detector'],
};

/**
 * Turn a detector on.
 */
export const useActivateDetector = () => {
  return useAction(ActivateDetectorDefinition);
};
