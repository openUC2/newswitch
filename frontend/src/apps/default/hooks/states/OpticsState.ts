import { z } from 'zod';
import { buildUseState, type StateDefinition } from '@/lib/arkitekt/state';

// --- Sub-Schemas ---
export const LightElementSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/light_element')
      .default('@newswitch/light_element'),
    name: z.string(),
    kind: z.string(),
    label: z.string(),
    facts: z.record(z.string(), z.string()),
    values: z.record(z.string(), z.string()),
  })
  .brand('@newswitch/light_element')
  .describe(
    'One cube on a light path: what is in place in it, as far as can be shown.',
  );
export type LightElement = z.input<typeof LightElementSchema>;
export type LightElementOutput = z.infer<typeof LightElementSchema>;

export const LightEdgeSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/light_edge')
      .default('@newswitch/light_edge'),
    source: z.string(),
    target: z.string(),
    via: z.string().nullable().optional(),
    side: z.string().nullable().optional(),
  })
  .brand('@newswitch/light_edge')
  .describe('Light going from one element to the next.');
export type LightEdge = z.input<typeof LightEdgeSchema>;
export type LightEdgeOutput = z.infer<typeof LightEdgeSchema>;

export const LightPathSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/light_path')
      .default('@newswitch/light_path'),
    detector: z.string(),
    elements: z.array(
      LightElementSchema.describe(
        'One cube on a light path: what is in place in it, as far as can be shown.',
      ),
    ),
    edges: z.array(
      LightEdgeSchema.describe('Light going from one element to the next.'),
    ),
  })
  .brand('@newswitch/light_path')
  .describe(
    "Every way light can take to one detector, as the description's edges say.",
  );
export type LightPath = z.input<typeof LightPathSchema>;
export type LightPathOutput = z.infer<typeof LightPathSchema>;

export const DetectorOpticsSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/detector_optics')
      .default('@newswitch/detector_optics'),
    name: z.string(),
    calibrated: z.boolean(),
    pixel_to_stage: z.array(z.array(z.number())),
    pixel_um: z.number(),
    field_width_um: z.number(),
    field_height_um: z.number(),
    spot_px: z.number(),
    expected_counts: z.number(),
    read_noise_counts: z.number(),
    depth_of_field_um: z.number(),
    band_nm: z.number().nullable().optional(),
    /** Every way light can take to one detector, as the description's edges say. */
    path: LightPathSchema.describe(
      "Every way light can take to one detector, as the description's edges say.",
    ),
  })
  .brand('@newswitch/detector_optics')
  .describe(
    'What a detector sees: as calibrated where that was measured, else as the optics predict.',
  );
export type DetectorOptics = z.input<typeof DetectorOpticsSchema>;
export type DetectorOpticsOutput = z.infer<typeof DetectorOpticsSchema>;

export const SourceOpticsSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/source_optics')
      .default('@newswitch/source_optics'),
    name: z.string(),
    shape: z.string(),
    side: z.string().nullable().optional(),
    field_um: z.number().nullable().optional(),
    thickness_um: z.number().nullable().optional(),
    reach_um: z.number().nullable().optional(),
    along: z.string().nullable().optional(),
  })
  .brand('@newswitch/source_optics')
  .describe("How a source's light lands on the sample.");
export type SourceOptics = z.input<typeof SourceOpticsSchema>;
export type SourceOpticsOutput = z.infer<typeof SourceOpticsSchema>;

export const OpticalChannelSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/optical_channel')
      .default('@newswitch/optical_channel'),
    source: z.string(),
    detector: z.string(),
    electrons: z.number(),
    band_nm: z.number().nullable().optional(),
  })
  .brand('@newswitch/optical_channel')
  .describe(
    'A source whose light gets through the sample to a detector: found, and never declared.',
  );
export type OpticalChannel = z.input<typeof OpticalChannelSchema>;
export type OpticalChannelOutput = z.infer<typeof OpticalChannelSchema>;

// --- Main Schema ---
export const OpticsStateSchema = z.object({
  detectors: z.record(
    z.string(),
    DetectorOpticsSchema.describe(
      'What a detector sees: as calibrated where that was measured, else as the optics predict.',
    ),
  ),
  sources: z.record(
    z.string(),
    SourceOpticsSchema.describe("How a source's light lands on the sample."),
  ),
  channels: z.array(
    OpticalChannelSchema.describe(
      'A source whose light gets through the sample to a detector: found, and never declared.',
    ),
  ),
});

// --- Type ---
export type OpticsState = z.infer<typeof OpticsStateSchema>;

// --- Definition ---
export const OpticsStateDefinition: StateDefinition<
  OpticsState,
  'OpticsState'
> = {
  appKey: 'default',
  key: 'OpticsState',
  schema: OpticsStateSchema,
};

/**
 * Hook to sync OpticsState
 */
export const useOpticsState = buildUseState<OpticsState>(OpticsStateDefinition);
