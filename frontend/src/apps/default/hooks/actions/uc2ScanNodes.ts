import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/rekuest/task';

// --- Shared Models ---

// --- Schemas ---
export const Uc2ScanNodesArgsSchema = z.object({
  timeout: z.number().nullable().optional(),
});
export const Uc2ScanNodesReturnSchema = z.object({
  return0: z.array(z.number()),
});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type Uc2ScanNodesArgs = z.input<typeof Uc2ScanNodesArgsSchema>;
export type Uc2ScanNodesReturn = z.infer<typeof Uc2ScanNodesReturnSchema>;

// --- Definition ---
export const Uc2ScanNodesDefinition: ActionDefinition<
  Uc2ScanNodesArgs,
  Uc2ScanNodesReturn
> = {
  name: 'uc2_scan_nodes',
  appKey: 'default',
  description:
    'Discover reachable UC2 bus nodes; the result also lands in UC2State.',
  argsSchema: Uc2ScanNodesArgsSchema,
  returnSchema: Uc2ScanNodesReturnSchema,
  lockKeys: [],
};

/**
 * Discover reachable UC2 bus nodes; the result also lands in UC2State.
 */
export const useUc2ScanNodes = () => {
  return useAction(Uc2ScanNodesDefinition);
};
