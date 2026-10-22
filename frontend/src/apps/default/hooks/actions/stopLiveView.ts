import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---

// --- Schemas ---
export const StopLiveViewArgsSchema = z.object({});
export const StopLiveViewReturnSchema = z.object({
  return0: z.string(),
});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type StopLiveViewArgs = z.input<typeof StopLiveViewArgsSchema>;
export type StopLiveViewReturn = z.infer<typeof StopLiveViewReturnSchema>;

// --- Definition ---
export const StopLiveViewDefinition: ActionDefinition<
  StopLiveViewArgs,
  StopLiveViewReturn
> = {
  name: 'stop_live_view',
  appKey: 'default',
  description:
    'Stop broadcasting frames to the video WebSocket endpoint.\n\nCall this to stop streaming frames captured by the detector\nto connected video clients.',
  argsSchema: StopLiveViewArgsSchema,
  returnSchema: StopLiveViewReturnSchema,
  lockKeys: ['camera_parameters'],
};

/**
 * Stop broadcasting frames to the video WebSocket endpoint.

Call this to stop streaming frames captured by the detector
to connected video clients.
 */
export const useStopLiveView = () => {
  return useAction(StopLiveViewDefinition);
};
