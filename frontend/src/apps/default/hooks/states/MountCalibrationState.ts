import { z } from 'zod';
import { buildUseState, type StateDefinition } from '@/lib/arkitekt/state';

// --- Sub-Schemas ---
export const MeasuredMountSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/measured_mount')
      .default('@newswitch/measured_mount'),
    /** The sample, by the cube holding it */
    sample: z.string().describe('The sample, by the cube holding it'),
    /** Which of its holders */
    holder: z.string().describe('Which of its holders'),
    /** Where the holder's origin is on the stage, along x */
    x_mm: z
      .number()
      .describe("Where the holder's origin is on the stage, along x"),
    /** ... and along y, from where homing puts the stage */
    y_mm: z
      .number()
      .describe('... and along y, from where homing puts the stage'),
    /** How far it is turned, as described */
    rotation_deg: z.number().describe('How far it is turned, as described'),
    /** How far that is from where it was taken to be, x and y */
    shift_um: z
      .array(z.number())
      .describe('How far that is from where it was taken to be, x and y'),
    /** Image scale measured on the way */
    pixel_um: z.number().describe('Image scale measured on the way'),
    /** The calibration store it was kept in, if it was */
    saved_to: z
      .string()
      .describe('The calibration store it was kept in, if it was')
      .nullable()
      .optional(),
  })
  .brand('@newswitch/measured_mount')
  .describe(
    'Where a holder was measured to sit on its stage, from its calibration slide.',
  );
export type MeasuredMount = z.input<typeof MeasuredMountSchema>;
export type MeasuredMountOutput = z.infer<typeof MeasuredMountSchema>;

// --- Main Schema ---
export const MountCalibrationStateSchema = z.object({
  sample: z.string(),
  holder: z.string(),
  holder_kind: z.string(),
  slide: z.string(),
  at: z.string(),
  mark: z.string(),
  mount_x_mm: z.number(),
  mount_y_mm: z.number(),
  busy: z.boolean(),
  step: z.string(),
  progress: z.number(),
  waiting: z.string().nullable().optional(),
  error: z.string().nullable().optional(),
  last: MeasuredMountSchema.describe(
    'Where a holder was measured to sit on its stage, from its calibration slide.',
  )
    .nullable()
    .optional(),
});

// --- Type ---
export type MountCalibrationState = z.infer<typeof MountCalibrationStateSchema>;

// --- Definition ---
export const MountCalibrationStateDefinition: StateDefinition<
  MountCalibrationState,
  'mount_calibration'
> = {
  appKey: 'default',
  key: 'mount_calibration',
  schema: MountCalibrationStateSchema,
};

/**
 * Hook to sync mount_calibration
 */
export const useMountCalibrationState = buildUseState<MountCalibrationState>(
  MountCalibrationStateDefinition,
);
