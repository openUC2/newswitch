import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---

// --- Schemas ---
export const StopLiveViewArgsSchema = z.object({});
export const StopLiveViewReturnSchema = z.object({
  /** Status message. */
  return0: z.string().describe('Status message.'),
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
  description: 'Stop streaming.',
  argsSchema: StopLiveViewArgsSchema,
  returnSchema: StopLiveViewReturnSchema,
  lockKeys: ['detector'],
};

/**
 * Stop streaming.
 */
export const useStopLiveView = () => {
  return useAction(StopLiveViewDefinition);
};
