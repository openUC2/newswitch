import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---

// --- Schemas ---
export const GalvoSetPositionArgsSchema = z.object({
  board: z.string(),
  x: z.number(),
  y: z.number(),
});
export const GalvoSetPositionReturnSchema = z.object({});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type GalvoSetPositionArgs = z.input<typeof GalvoSetPositionArgsSchema>;
export type GalvoSetPositionReturn = z.infer<
  typeof GalvoSetPositionReturnSchema
>;

// --- Definition ---
export const GalvoSetPositionDefinition: ActionDefinition<
  GalvoSetPositionArgs,
  GalvoSetPositionReturn
> = {
  name: 'galvo_set_position',
  appKey: 'default',
  description:
    "Move a board's galvo mirror to an absolute XY position (DAC counts).",
  argsSchema: GalvoSetPositionArgsSchema,
  returnSchema: GalvoSetPositionReturnSchema,
  lockKeys: ['galvo'],
};

/**
 * Move a board's galvo mirror to an absolute XY position (DAC counts).
 */
export const useGalvoSetPosition = () => {
  return useAction(GalvoSetPositionDefinition);
};
