import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---
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

// --- Schemas ---
export const CalibrateMountArgsSchema = z.object({
  /** Which sample, by the cube holding it; may be left out when there is one. */
  sample: z
    .string()
    .describe(
      'Which sample, by the cube holding it; may be left out when there is one.',
    )
    .nullable()
    .optional(),
  /** Keep the mount in the calibration store (else it holds until the next start). */
  save: z
    .boolean()
    .describe(
      'Keep the mount in the calibration store (else it holds until the next start).',
    )
    .nullable()
    .optional(),
  /** Hold for a person to check the light is on the mark before looking for it. */
  confirm: z
    .boolean()
    .describe(
      'Hold for a person to check the light is on the mark before looking for it.',
    )
    .nullable()
    .optional(),
});
export const CalibrateMountReturnSchema = z.object({
  /** Where a holder was measured to sit on its stage, from its calibration slide. */
  return0: MeasuredMountSchema.describe(
    'Where a holder was measured to sit on its stage, from its calibration slide.',
  ),
});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type CalibrateMountArgs = z.input<typeof CalibrateMountArgsSchema>;
export type CalibrateMountReturn = z.infer<typeof CalibrateMountReturnSchema>;

// --- Definition ---
export const CalibrateMountDefinition: ActionDefinition<
  CalibrateMountArgs,
  CalibrateMountReturn
> = {
  name: 'calibrate_mount',
  appKey: 'default',
  description:
    "Measure where the calibration's holder sits on the stage, from its calibration slide.\n\nHomes what the calibration says (the stage's 0 is there), sets what it says (light, focus),\ngoes where the holder's mount puts the mark and holds: someone checks that the stage was homed\nand the light falls on the calibration slide's mark, and approves. Then it looks for the mark\naround there, brings it into the middle of the image and takes the mount from where the stage\nis. The mount is used from then on, and kept in the calibration store.",
  argsSchema: CalibrateMountArgsSchema,
  returnSchema: CalibrateMountReturnSchema,
  lockKeys: ['detector', 'motion', 'tune'],
};

/**
 * Measure where the calibration's holder sits on the stage, from its calibration slide.

Homes what the calibration says (the stage's 0 is there), sets what it says (light, focus),
goes where the holder's mount puts the mark and holds: someone checks that the stage was homed
and the light falls on the calibration slide's mark, and approves. Then it looks for the mark
around there, brings it into the middle of the image and takes the mount from where the stage
is. The mount is used from then on, and kept in the calibration store.
 */
export const useCalibrateMount = () => {
  return useAction(CalibrateMountDefinition);
};
