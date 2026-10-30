import { z } from 'zod';
import { buildUseState, type StateDefinition } from '@/lib/arkitekt/state';

// --- Sub-Schemas ---
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
    /** The transformation hash of the light path configuration this affine matrix corresponds to */
    light_path_state_hash: z
      .string()
      .describe(
        'The transformation hash of the light path configuration this affine matrix corresponds to',
      ),
  })
  .brand('@newswitch/calibrated_light_path')
  .describe('Shared state for affine transformation parameters.');
export type CalibratedLightPath = z.input<typeof CalibratedLightPathSchema>;
export type CalibratedLightPathOutput = z.infer<
  typeof CalibratedLightPathSchema
>;

// --- Main Schema ---
export const CalibrationStateSchema = z.object({
  calibrated_light_paths: z.array(
    CalibratedLightPathSchema.describe(
      'Shared state for affine transformation parameters.',
    ),
  ),
});

// --- Type ---
export type CalibrationState = z.infer<typeof CalibrationStateSchema>;

// --- Definition ---
export const CalibrationStateDefinition: StateDefinition<
  CalibrationState,
  'CalibrationState'
> = {
  appKey: 'default',
  key: 'CalibrationState',
  schema: CalibrationStateSchema,
};

/**
 * Hook to sync CalibrationState
 */
export const useCalibrationState = buildUseState<CalibrationState>(
  CalibrationStateDefinition,
);
