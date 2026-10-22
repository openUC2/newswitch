import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---

// --- Schemas ---
export const StartLiveViewArgsSchema = z.object({});
export const StartLiveViewReturnSchema = z.object({
  return0: z.string(),
});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type StartLiveViewArgs = z.input<typeof StartLiveViewArgsSchema>;
export type StartLiveViewReturn = z.infer<typeof StartLiveViewReturnSchema>;

// --- Definition ---
export const StartLiveViewDefinition: ActionDefinition<
  StartLiveViewArgs,
  StartLiveViewReturn
> = {
  name: 'start_live_view',
  appKey: 'default',
  description:
    'Start broadcasting frames to the video WebSocket endpoint.\n\nCall this to begin streaming frames captured by the detector\nto connected video clients.',
  argsSchema: StartLiveViewArgsSchema,
  returnSchema: StartLiveViewReturnSchema,
  lockKeys: ['camera_parameters'],
};

/**
 * Start broadcasting frames to the video WebSocket endpoint.

Call this to begin streaming frames captured by the detector
to connected video clients.
 */
export const useStartLiveView = () => {
  return useAction(StartLiveViewDefinition);
};
