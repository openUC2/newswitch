import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---

// --- Schemas ---
export const ActivateDetectorArgsSchema = z.object({
  /** Detector slot number to activate */
  slot: z.number().describe('Detector slot number to activate'),
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
  description: 'Activate a detector by its slot number.',
  argsSchema: ActivateDetectorArgsSchema,
  returnSchema: ActivateDetectorReturnSchema,
  lockKeys: ['camera_parameters'],
};

/**
 * Activate a detector by its slot number.
 */
export const useActivateDetector = () => {
  return useAction(ActivateDetectorDefinition);
};
