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
    'How a step along a column and along a row moves on the sample, for one light path: as the\n    optics predict it, or as it was measured (`newswitch.calibration`).',
  );
export type CalibratedLightPath = z.input<typeof CalibratedLightPathSchema>;
export type CalibratedLightPathOutput = z.infer<
  typeof CalibratedLightPathSchema
>;

export const CalibratedMountSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/calibrated_mount')
      .default('@newswitch/calibrated_mount'),
    /** The sample, by the cube holding it */
    sample: z.string().describe('The sample, by the cube holding it'),
    /** Which of its holders */
    holder: z.string().describe('Which of its holders'),
    /** Off its design's place, along x */
    offset_x_um: z.number().describe("Off its design's place, along x"),
    /** ... and along y */
    offset_y_um: z.number().describe('... and along y'),
    /** Turned further than its design says */
    rotation_deg: z.number().describe('Turned further than its design says'),
    /** When it was measured, ISO 8601 */
    measured: z.string().describe('When it was measured, ISO 8601'),
  })
  .brand('@newswitch/calibrated_mount')
  .describe(
    'How far a holder sits from where its design puts it (its `mount`): what is kept of it.',
  );
export type CalibratedMount = z.input<typeof CalibratedMountSchema>;
export type CalibratedMountOutput = z.infer<typeof CalibratedMountSchema>;

// --- Main Schema ---
export const CalibrationStateSchema = z.object({
  calibrated_light_paths: z.array(
    CalibratedLightPathSchema.describe(
      'How a step along a column and along a row moves on the sample, for one light path: as the\n    optics predict it, or as it was measured (`newswitch.calibration`).',
    ),
  ),
  mounts: z.array(
    CalibratedMountSchema.describe(
      'How far a holder sits from where its design puts it (its `mount`): what is kept of it.',
    ),
  ),
  design: z.string(),
  stale: z.boolean(),
  stored_design: z.string().nullable().optional(),
  saved: z.string().nullable().optional(),
  store: z.string().nullable().optional(),
});

// --- Type ---
export type CalibrationState = z.infer<typeof CalibrationStateSchema>;

// --- Definition ---
export const CalibrationStateDefinition: StateDefinition<
  CalibrationState,
  'calibration'
> = {
  appKey: 'default',
  key: 'calibration',
  schema: CalibrationStateSchema,
};

/**
 * Hook to sync calibration
 */
export const useCalibrationState = buildUseState<CalibrationState>(
  CalibrationStateDefinition,
);
