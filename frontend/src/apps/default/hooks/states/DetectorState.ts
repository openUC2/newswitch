import { z } from 'zod';
import { buildUseState, type StateDefinition } from '@/lib/arkitekt/state';

// --- Sub-Schemas ---
export const DetectorAxisSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/detector_axis')
      .default('@newswitch/detector_axis'),
    name: z.string(),
    domain: z.string(),
    unit: z.string(),
    size: z.number().nullable().optional(),
    step: z.number().nullable().optional(),
    delivered_by: z.string(),
    binnable: z.boolean(),
    window_start: z.number(),
    window_size: z.number().nullable().optional(),
    binning: z.number(),
    delivered_size: z.number().nullable().optional(),
  })
  .brand('@newswitch/detector_axis')
  .describe(
    'One axis a detector delivers, measuring a domain of the sample: space, spectrum, microtime.',
  );
export type DetectorAxis = z.input<typeof DetectorAxisSchema>;
export type DetectorAxisOutput = z.infer<typeof DetectorAxisSchema>;

export const DetectorSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/detector')
      .default('@newswitch/detector'),
    name: z.string(),
    is_active: z.boolean(),
    data_type: z.string(),
    colors: z.array(z.string()),
    axes: z.array(
      DetectorAxisSchema.describe(
        'One axis a detector delivers, measuring a domain of the sample: space, spectrum, microtime.',
      ),
    ),
    quantity: z.string(),
    unit: z.string(),
    reading: z.number().nullable().optional(),
    measures_light: z.boolean(),
    current_exposure_ms: z.number().nullable().optional(),
    current_gain: z.number().nullable().optional(),
    current_frame_rate: z.number().nullable().optional(),
    is_recording: z.boolean(),
    recording_file: z.string().nullable().optional(),
    manufacturer: z.string().nullable().optional(),
    model: z.string().nullable().optional(),
    serial_number: z.string().nullable().optional(),
    connection_type: z.string().nullable().optional(),
    device_index: z.number().nullable().optional(),
    buffer_size: z.number().nullable().optional(),
    store_image_data: z.boolean().nullable().optional(),
    pixel_format: z.string().nullable().optional(),
  })
  .brand('@newswitch/detector')
  .describe(
    "What measures the sample: along its axes, or with none, at one point. Its name is its cube's.",
  );
export type Detector = z.input<typeof DetectorSchema>;
export type DetectorOutput = z.infer<typeof DetectorSchema>;

// --- Main Schema ---
export const DetectorStateSchema = z.object({
  is_acquiring: z.boolean(),
  detectors: z.array(
    DetectorSchema.describe(
      "What measures the sample: along its axes, or with none, at one point. Its name is its cube's.",
    ),
  ),
});

// --- Type ---
export type DetectorState = z.infer<typeof DetectorStateSchema>;

// --- Definition ---
export const DetectorStateDefinition: StateDefinition<
  DetectorState,
  'DetectorState'
> = {
  appKey: 'default',
  key: 'DetectorState',
  schema: DetectorStateSchema,
};

/**
 * Hook to sync DetectorState
 */
export const useDetectorState = buildUseState<DetectorState>(
  DetectorStateDefinition,
);
