import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---
export const CalibratedLightPathSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/calibrated_light_path')
      .default('@newswitch/calibrated_light_path'),
    /** 4x4 affine transformation matrix for mapping between coordinate systems */
    affine_matrix: z
      .array(z.array(z.number()))
      .describe(
        '4x4 affine transformation matrix for mapping between coordinate systems',
      ),
    /** Field of view width in micrometers */
    fov_width: z.number().describe('Field of view width in micrometers'),
    /** Field of view height in micrometers */
    fov_height: z.number().describe('Field of view height in micrometers'),
    /** Hash of the light path configuration this affine matrix corresponds to */
    light_path_state_hash: z
      .string()
      .describe(
        'Hash of the light path configuration this affine matrix corresponds to',
      ),
  })
  .brand('@newswitch/calibrated_light_path')
  .describe('Shared state for affine transformation parameters.');
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
      'Shared state for affine transformation parameters.',
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
    'Calibrate the light path of every active detector: its pixel-to-stage transform.\n\nThe stage moves `CALIBRATION_STEP_UM` in x only, then in y only, at a fixed focus; the\nimage shifts give the pixel scale (rotation and flip included), stored per light path\nfor the frames acquired through it. The stage ends where it started.',
  argsSchema: CalibrateLightPathArgsSchema,
  returnSchema: CalibrateLightPathReturnSchema,
  lockKeys: ['camera_parameters', 'stage_position'],
};

/**
 * Calibrate the light path of every active detector: its pixel-to-stage transform.

The stage moves `CALIBRATION_STEP_UM` in x only, then in y only, at a fixed focus; the
image shifts give the pixel scale (rotation and flip included), stored per light path
for the frames acquired through it. The stage ends where it started.
 */
export const useCalibrateLightPath = () => {
  return useAction(CalibrateLightPathDefinition);
};
