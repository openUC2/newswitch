import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---

// --- Schemas ---
export const DeactivateDetectorArgsSchema = z.object({
  /** Detector slot number to deactivate */
  slot: z.number().describe('Detector slot number to deactivate'),
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
  description: 'Deactivate a detector by its slot number.',
  argsSchema: DeactivateDetectorArgsSchema,
  returnSchema: DeactivateDetectorReturnSchema,
  lockKeys: ['camera_parameters'],
};

/**
 * Deactivate a detector by its slot number.
 */
export const useDeactivateDetector = () => {
  return useAction(DeactivateDetectorDefinition);
};
