import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---

// --- Schemas ---
export const StartLiveViewArgsSchema = z.object({});
export const StartLiveViewReturnSchema = z.object({
  /** Status message. */
  return0: z.string().describe('Status message.'),
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
  description: 'Start streaming every active detector.',
  argsSchema: StartLiveViewArgsSchema,
  returnSchema: StartLiveViewReturnSchema,
  lockKeys: ['detector'],
};

/**
 * Start streaming every active detector.
 */
export const useStartLiveView = () => {
  return useAction(StartLiveViewDefinition);
};
