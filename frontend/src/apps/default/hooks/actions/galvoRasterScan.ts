import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/rekuest/task';

// --- Shared Models ---

// --- Schemas ---
export const GalvoRasterScanArgsSchema = z.object({
  x_min: z.number().nullable().optional(),
  x_max: z.number().nullable().optional(),
  y_min: z.number().nullable().optional(),
  y_max: z.number().nullable().optional(),
  nx: z.number().nullable().optional(),
  ny: z.number().nullable().optional(),
  pixel_dwell_us: z.number().nullable().optional(),
  trigger_mode: z.number().nullable().optional(),
  bidirectional: z.boolean().nullable().optional(),
});
export const GalvoRasterScanReturnSchema = z.object({});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type GalvoRasterScanArgs = z.input<typeof GalvoRasterScanArgsSchema>;
export type GalvoRasterScanReturn = z.infer<typeof GalvoRasterScanReturnSchema>;

// --- Definition ---
export const GalvoRasterScanDefinition: ActionDefinition<
  GalvoRasterScanArgs,
  GalvoRasterScanReturn
> = {
  name: 'galvo_raster_scan',
  appKey: 'default',
  description:
    'Configure and start a galvo raster scan (camera trigger per pixel by default).',
  argsSchema: GalvoRasterScanArgsSchema,
  returnSchema: GalvoRasterScanReturnSchema,
  lockKeys: ['galvo'],
};

/**
 * Configure and start a galvo raster scan (camera trigger per pixel by default).
 */
export const useGalvoRasterScan = () => {
  return useAction(GalvoRasterScanDefinition);
};
