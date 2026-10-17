import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/rekuest/task';

// --- Shared Models ---

// --- Schemas ---
export const GalvoStopArgsSchema = z.object({});
export const GalvoStopReturnSchema = z.object({});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type GalvoStopArgs = z.input<typeof GalvoStopArgsSchema>;
export type GalvoStopReturn = z.infer<typeof GalvoStopReturnSchema>;

// --- Definition ---
export const GalvoStopDefinition: ActionDefinition<
  GalvoStopArgs,
  GalvoStopReturn
> = {
  name: 'galvo_stop',
  appKey: 'default',
  description: 'Stop any active galvo scan (lock-free so it works mid-scan).',
  argsSchema: GalvoStopArgsSchema,
  returnSchema: GalvoStopReturnSchema,
  lockKeys: [],
};

/**
 * Stop any active galvo scan (lock-free so it works mid-scan).
 */
export const useGalvoStop = () => {
  return useAction(GalvoStopDefinition);
};
