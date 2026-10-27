import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/rekuest/task';

// --- Shared Models ---

// --- Schemas ---
export const StartLiveViewAndSaveToDiskArgsSchema = z.object({});
export const StartLiveViewAndSaveToDiskReturnSchema = z.object({
  return0: z.string(),
});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type StartLiveViewAndSaveToDiskArgs = z.input<
  typeof StartLiveViewAndSaveToDiskArgsSchema
>;
export type StartLiveViewAndSaveToDiskReturn = z.infer<
  typeof StartLiveViewAndSaveToDiskReturnSchema
>;

// --- Definition ---
export const StartLiveViewAndSaveToDiskDefinition: ActionDefinition<
  StartLiveViewAndSaveToDiskArgs,
  StartLiveViewAndSaveToDiskReturn
> = {
  name: 'start_live_view_and_save_to_disk',
  appKey: 'default',
  description:
    'Start broadcasting frames and write every image of the active detectors to disk.\n\nLike start_live_view; the images also go to a recording file per detector until\nstop_live_view or until the detector is deactivated. The virtual detector cannot\nrecord and fails.',
  argsSchema: StartLiveViewAndSaveToDiskArgsSchema,
  returnSchema: StartLiveViewAndSaveToDiskReturnSchema,
  lockKeys: ['camera_parameters'],
};

/**
 * Start broadcasting frames and write every image of the active detectors to disk.

Like start_live_view; the images also go to a recording file per detector until
stop_live_view or until the detector is deactivated. The virtual detector cannot
record and fails.
 */
export const useStartLiveViewAndSaveToDisk = () => {
  return useAction(StartLiveViewAndSaveToDiskDefinition);
};
