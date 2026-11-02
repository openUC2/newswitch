import { z } from 'zod';
import { buildUseState, type StateDefinition } from '@/lib/arkitekt/state';

// --- Sub-Schemas ---
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

// --- Main Schema ---
export const CalibrationStateSchema = z.object({
  calibrated_light_paths: z.array(
    CalibratedLightPathSchema.describe(
      'How a step along a column and along a row moves on the sample, for one light path.',
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
