import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---
export const ScaleSchema = z
  .object({
    __identifier: z.literal('@newswitch/scale').default('@newswitch/scale'),
    x: z.number(),
    y: z.number(),
    z: z.number(),
    cached_id: z.string().nullable().optional(),
    affine_matrix: z.array(z.array(z.number())).nullable().optional(),
  })
  .brand('@newswitch/scale')
  .describe('Represents a scale factor for a 3D volume.');
export type Scale = z.input<typeof ScaleSchema>;
export type ScaleOutput = z.infer<typeof ScaleSchema>;

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

export const LightPathSnapshotSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/light_path_snapshot')
      .default('@newswitch/light_path_snapshot'),
    key: z.string(),
    hash: z.string(),
    elements: z.array(
      LightElementSchema.describe(
        'One cube on a light path: what is in place in it, as far as can be shown.',
      ),
    ),
    edges: z.array(
      LightEdgeSchema.describe('Light going from one element to the next.'),
    ),
  })
  .brand('@newswitch/light_path_snapshot')
  .describe(
    "A light path as it was for an image, and what that image's calibration depends on.",
  );
export type LightPathSnapshot = z.input<typeof LightPathSnapshotSchema>;
export type LightPathSnapshotOutput = z.infer<typeof LightPathSnapshotSchema>;

export const MetadataSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/metadata')
      .default('@newswitch/metadata'),
    affine_matrix: z.array(z.array(z.number())),
    fov_width: z.number(),
    fov_height: z.number(),
    /** A light path as it was for an image, and what that image's calibration depends on. */
    light_state: LightPathSnapshotSchema.describe(
      "A light path as it was for an image, and what that image's calibration depends on.",
    ),
    acquisition_time: z.string(),
    colormap: z.string(),
    min_value: z.number().nullable().optional(),
    max_value: z.number().nullable().optional(),
  })
  .brand('@newswitch/metadata')
  .describe(
    'Data class representing metadata for an image, including its ID and affine transformation matrix.',
  );
export type Metadata = z.input<typeof MetadataSchema>;
export type MetadataOutput = z.infer<typeof MetadataSchema>;

export const ArrayMetadataSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/array_metadata')
      .default('@newswitch/array_metadata'),
    min_value: z.number(),
    max_value: z.number(),
  })
  .brand('@newswitch/array_metadata')
  .describe(
    'Metadata for a raw array before it is saved as an image, including the light path and acquisition settings.',
  );
export type ArrayMetadata = z.input<typeof ArrayMetadataSchema>;
export type ArrayMetadataOutput = z.infer<typeof ArrayMetadataSchema>;

export const FrameSchema = z
  .object({
    __identifier: z.literal('@newswitch/frame').default('@newswitch/frame'),
    id: z.string(),
    scales: z.array(
      ScaleSchema.describe('Represents a scale factor for a 3D volume.'),
    ),
    /** Data class representing metadata for an image, including its ID and affine transformation matrix. */
    metadata: MetadataSchema.describe(
      'Data class representing metadata for an image, including its ID and affine transformation matrix.',
    ),
    /** Metadata for a raw array before it is saved as an image, including the light path and acquisition settings. */
    array_metadata: ArrayMetadataSchema.describe(
      'Metadata for a raw array before it is saved as an image, including the light path and acquisition settings.',
    ),
  })
  .brand('@newswitch/frame')
  .describe('Represents a single 3D volume captured by the detector.');
export type Frame = z.input<typeof FrameSchema>;
export type FrameOutput = z.infer<typeof FrameSchema>;

// --- Schemas ---
export const ScanRegionArgsSchema = z.object({
  /** Defines the order in which stage positions are visited during acquisition. */
  scan_order: z.union([
    z
      .literal('SNAKE_ROW')
      .describe(
        'Defines the order in which stage positions are visited during acquisition.',
      ),
    z
      .literal('SNAKE_COL')
      .describe(
        'Defines the order in which stage positions are visited during acquisition.',
      ),
    z
      .literal('RASTER_ROW')
      .describe(
        'Defines the order in which stage positions are visited during acquisition.',
      ),
    z
      .literal('RASTER_COL')
      .describe(
        'Defines the order in which stage positions are visited during acquisition.',
      ),
  ]),
  start_x: z.number(),
  start_y: z.number(),
  end_x: z.number(),
  end_y: z.number(),
  overlap: z.number().nullable().optional(),
  /** The detector to calculate the FOV for (all other detectors will follow). If None, use the first active detector. */
  detector_slot: z
    .number()
    .describe(
      'The detector to calculate the FOV for (all other detectors will follow). If None, use the first active detector.',
    )
    .nullable()
    .optional(),
});
export const ScanRegionReturnSchema = z.object({
  /** The frames, in the order acquired. */
  return0: z.array(
    FrameSchema.describe(
      'Represents a single 3D volume captured by the detector.',
    ),
  ),
});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type ScanRegionArgs = z.input<typeof ScanRegionArgsSchema>;
export type ScanRegionReturn = z.infer<typeof ScanRegionReturnSchema>;

// --- Definition ---
export const ScanRegionDefinition: ActionDefinition<
  ScanRegionArgs,
  ScanRegionReturn
> = {
  name: 'scan_region',
  appKey: 'default',
  description:
    'Scan a rectangular region of the stage tile by tile.\n\nThe region from (start_x, start_y) to (end_x, end_y) (stage micrometres) is covered\nwith fields of view of the detector (`detector_slot`, else the first active one),\noverlapping by `overlap`, visited in `scan_order`; every active detector acquires a\nframe at each tile.',
  argsSchema: ScanRegionArgsSchema,
  returnSchema: ScanRegionReturnSchema,
  lockKeys: ['camera_parameters', 'expanse_state', 'io', 'stage_position'],
};

/**
 * Scan a rectangular region of the stage tile by tile.

The region from (start_x, start_y) to (end_x, end_y) (stage micrometres) is covered
with fields of view of the detector (`detector_slot`, else the first active one),
overlapping by `overlap`, visited in `scan_order`; every active detector acquires a
frame at each tile.
 */
export const useScanRegion = () => {
  return useAction(ScanRegionDefinition);
};
