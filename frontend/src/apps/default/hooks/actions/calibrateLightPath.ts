import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---
export const CalibratedLightPathSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/calibrated_light_path')
      .default('@newswitch/calibrated_light_path'),
    /** Pixel to sample micrometres, without where it looks: its 2x2 is the scale */
    affine_matrix: z
      .array(z.array(z.number()))
      .describe(
        'Pixel to sample micrometres, without where it looks: its 2x2 is the scale',
      ),
    /** Of what changes where a pixel looks: this matrix holds for as long as it does */
    key: z
      .string()
      .describe(
        'Of what changes where a pixel looks: this matrix holds for as long as it does',
      ),
  })
  .brand('@newswitch/calibrated_light_path')
  .describe(
    'How a step along a column and along a row moves on the sample, for one light path.',
  );
export type CalibratedLightPath = z.input<typeof CalibratedLightPathSchema>;
export type CalibratedLightPathOutput = z.infer<
  typeof CalibratedLightPathSchema
>;

// --- Schemas ---
export const CalibrateLightPathArgsSchema = z.object({});
export const CalibrateLightPathReturnSchema = z.object({
  /** The calibrated light paths. */
  return0: z.array(
    CalibratedLightPathSchema.describe(
      'How a step along a column and along a row moves on the sample, for one light path.',
    ),
  ),
});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type CalibrateLightPathArgs = z.input<
  typeof CalibrateLightPathArgsSchema
>;
export type CalibrateLightPathReturn = z.infer<
  typeof CalibrateLightPathReturnSchema
>;

// --- Definition ---
export const CalibrateLightPathDefinition: ActionDefinition<
  CalibrateLightPathArgs,
  CalibrateLightPathReturn
> = {
  name: 'calibrate_light_path',
  appKey: 'default',
  description:
    'Calibrate the light path of every active detector: its pixel-to-stage transform.\n\nThe stage moves in x only, then in y only, at a fixed focus, by as much as shifts the image\nby `SHIFT_OF_FRAME`; the image shifts give the pixel scale (rotation and flip included),\nstored per light path for the frames acquired through it. The stage ends where it started.',
  argsSchema: CalibrateLightPathArgsSchema,
  returnSchema: CalibrateLightPathReturnSchema,
  lockKeys: ['detector', 'motion'],
};

/**
 * Calibrate the light path of every active detector: its pixel-to-stage transform.

The stage moves in x only, then in y only, at a fixed focus, by as much as shifts the image
by `SHIFT_OF_FRAME`; the image shifts give the pixel scale (rotation and flip included),
stored per light path for the frames acquired through it. The stage ends where it started.
 */
export const useCalibrateLightPath = () => {
  return useAction(CalibrateLightPathDefinition);
};
