import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/rekuest/task';

// --- Shared Models ---
export const GalvoStatusSchema = z
  .object({
    __identifier: z.literal('galvo_status').default('galvo_status'),
    raw: z.number(),
    moving: z.boolean(),
    scan_active: z.boolean(),
    scan_complete: z.boolean(),
    error: z.boolean(),
  })
  .brand('galvo_status')
  .describe('Decoded galvo scanner status flags.');
export type GalvoStatus = z.input<typeof GalvoStatusSchema>;
export type GalvoStatusOutput = z.infer<typeof GalvoStatusSchema>;

// --- Schemas ---
export const GalvoGetStatusArgsSchema = z.object({});
export const GalvoGetStatusReturnSchema = z.object({
  /** Decoded galvo scanner status flags. */
  return0: GalvoStatusSchema.describe('Decoded galvo scanner status flags.'),
});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type GalvoGetStatusArgs = z.input<typeof GalvoGetStatusArgsSchema>;
export type GalvoGetStatusReturn = z.infer<typeof GalvoGetStatusReturnSchema>;

// --- Definition ---
export const GalvoGetStatusDefinition: ActionDefinition<
  GalvoGetStatusArgs,
  GalvoGetStatusReturn
> = {
  name: 'galvo_get_status',
  appKey: 'default',
  description:
    'Read decoded galvo status flags (moving, scan_active, error, ...).',
  argsSchema: GalvoGetStatusArgsSchema,
  returnSchema: GalvoGetStatusReturnSchema,
  lockKeys: [],
};

/**
 * Read decoded galvo status flags (moving, scan_active, error, ...).
 */
export const useGalvoGetStatus = () => {
  return useAction(GalvoGetStatusDefinition);
};
