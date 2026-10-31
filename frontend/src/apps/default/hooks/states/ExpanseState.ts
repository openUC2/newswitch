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

export const ImageSchema = z
  .object({
    __identifier: z.literal('@newswitch/image').default('@newswitch/image'),
    id: z.string(),
    /** Data class representing metadata for an image, including its ID and affine transformation matrix. */
    metadata: MetadataSchema.describe(
      'Data class representing metadata for an image, including its ID and affine transformation matrix.',
    ),
  })
  .brand('@newswitch/image')
  .describe('Represents a single image captured by the detector.');
export type Image = z.input<typeof ImageSchema>;
export type ImageOutput = z.infer<typeof ImageSchema>;

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

// --- Main Schema ---
export const ExpanseStateSchema = z.object({
  current_id: z.string(),
  current_images: z.array(
    ImageSchema.describe('Represents a single image captured by the detector.'),
  ),
  current_frames: z.array(
    FrameSchema.describe(
      'Represents a single 3D volume captured by the detector.',
    ),
  ),
});

// --- Type ---
export type ExpanseState = z.infer<typeof ExpanseStateSchema>;

// --- Definition ---
export const ExpanseStateDefinition: StateDefinition<
  ExpanseState,
  'ExpanseState'
> = {
  appKey: 'default',
  key: 'ExpanseState',
  schema: ExpanseStateSchema,
};

/**
 * Hook to sync ExpanseState
 */
export const useExpanseState = buildUseState<ExpanseState>(
  ExpanseStateDefinition,
);
