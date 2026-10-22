import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---

// --- Schemas ---
export const FailingCameraArgsSchema = z.object({
  intensity: z.number(),
});
export const FailingCameraReturnSchema = z.object({
  return0: z.string(),
});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type FailingCameraArgs = z.input<typeof FailingCameraArgsSchema>;
export type FailingCameraReturn = z.infer<typeof FailingCameraReturnSchema>;

// --- Definition ---
export const FailingCameraDefinition: ActionDefinition<
  FailingCameraArgs,
  FailingCameraReturn
> = {
  name: 'failing_camera',
  appKey: 'default',
  description: 'A function that always fails to test lock release.',
  argsSchema: FailingCameraArgsSchema,
  returnSchema: FailingCameraReturnSchema,
  lockKeys: ['stage_position'],
};

/**
 * A function that always fails to test lock release.
 */
export const useFailingCamera = () => {
  return useAction(FailingCameraDefinition);
};
