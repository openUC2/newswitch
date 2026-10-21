import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/rekuest/task';

// --- Shared Models ---
export const DetectorSchema = z
  .object({
    __identifier: z.literal('detector').default('detector'),
    slot: z.number(),
    name: z.string(),
    width: z.number(),
    height: z.number(),
    is_active: z.boolean(),
    current_exposure_time: z.number(),
    current_gain: z.number(),
    current_colormap: z.string(),
    pixel_size_um: z.number(),
    preset_exposure_times: z.array(z.number()),
    max_exposure_time: z.number(),
    min_exposure_time: z.number(),
    max_gain: z.number(),
    min_gain: z.number(),
    is_acquiring: z.boolean(),
    data_type: z.string(),
    key: z.string().nullable().optional(),
    manufacturer: z.string().nullable().optional(),
    model: z.string().nullable().optional(),
    serial_number: z.string().nullable().optional(),
    connection_type: z.string().nullable().optional(),
    device_index: z.number().nullable().optional(),
    buffer_size: z.number().nullable().optional(),
    store_image_data: z.boolean().nullable().optional(),
    pixel_format: z.string().nullable().optional(),
    sensor_width: z.number(),
    sensor_height: z.number(),
    pixel_pitch_um: z.number().nullable().optional(),
    current_frame_rate: z.number().nullable().optional(),
    current_binning: z.number(),
    current_roi: z.array(z.number()).nullable().optional(),
    min_frame_rate: z.number().nullable().optional(),
    max_frame_rate: z.number().nullable().optional(),
    available_binnings: z.array(z.number()),
    can_set_exposure: z.boolean(),
    can_set_gain: z.boolean(),
    can_set_frame_rate: z.boolean(),
    can_set_binning: z.boolean(),
    can_set_roi: z.boolean(),
    is_recording: z.boolean(),
    recording_file: z.string().nullable().optional(),
  })
  .brand('detector')
  .describe('Shared state for detector parameters.');
export type Detector = z.input<typeof DetectorSchema>;
export type DetectorOutput = z.infer<typeof DetectorSchema>;

// --- Schemas ---
export const UpdateDetectorArgsSchema = z.object({
  /** Detector slot number */
  slot: z.number().describe('Detector slot number'),
  /** Exposure time in seconds (optional) */
  exposure_time: z
    .number()
    .describe('Exposure time in seconds (optional)')
    .nullable()
    .optional(),
  /** Gain value (optional) */
  gain: z.number().describe('Gain value (optional)').nullable().optional(),
});
export const UpdateDetectorReturnSchema = z.object({
  /** Shared state for detector parameters. */
  return0: DetectorSchema.describe('Shared state for detector parameters.'),
});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type UpdateDetectorArgs = z.input<typeof UpdateDetectorArgsSchema>;
export type UpdateDetectorReturn = z.infer<typeof UpdateDetectorReturnSchema>;

// --- Definition ---
export const UpdateDetectorDefinition: ActionDefinition<
  UpdateDetectorArgs,
  UpdateDetectorReturn
> = {
  name: 'update_detector',
  appKey: 'default',
  description: 'Update detector settings.',
  argsSchema: UpdateDetectorArgsSchema,
  returnSchema: UpdateDetectorReturnSchema,
  lockKeys: ['camera_parameters'],
};

/**
 * Update detector settings.
 */
export const useUpdateDetector = () => {
  return useAction(UpdateDetectorDefinition);
};
