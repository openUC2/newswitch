import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';
import { createIndexedUnion } from './utils';

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

export const ObjectiveKubeStateSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/objective_kube_state')
      .default('@newswitch/objective_kube_state'),
    kube_id: z.string(),
    slot_id: z.number(),
    /** Affine transformation matrix of the kube */
    affine_matrix: z
      .array(z.array(z.number()))
      .describe('Affine transformation matrix of the kube'),
    /** Model name of the objective lens (e.g., 'Plan-Apochromat 63x/1.4 Oil DIC M27') */
    model_name: z
      .string()
      .describe(
        "Model name of the objective lens (e.g., 'Plan-Apochromat 63x/1.4 Oil DIC M27')",
      )
      .nullable()
      .optional(),
    /** Path to a file containing the physical model of the objective lens */
    model_file: z
      .string()
      .describe(
        'Path to a file containing the physical model of the objective lens',
      )
      .nullable()
      .optional(),
  })
  .brand('@newswitch/objective_kube_state')
  .describe(
    'Data class representing metadata for a kube, including its ID and affine transformation matrix.',
  );
export type ObjectiveKubeState = z.input<typeof ObjectiveKubeStateSchema>;
export type ObjectiveKubeStateOutput = z.infer<typeof ObjectiveKubeStateSchema>;

export const DetectorKubeStateSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/detector_kube_state')
      .default('@newswitch/detector_kube_state'),
    kube_id: z.string(),
    gain: z.number(),
    exposure_time: z.number(),
    /** Affine transformation matrix of the kube */
    affine_matrix: z
      .array(z.array(z.number()))
      .describe('Affine transformation matrix of the kube'),
    /** Model name of the detector (e.g., 'Pco Edge 4.2m') */
    model_name: z
      .string()
      .describe("Model name of the detector (e.g., 'Pco Edge 4.2m')")
      .nullable()
      .optional(),
    /** Path to a file containing the physical model of the detector */
    model_file: z
      .string()
      .describe('Path to a file containing the physical model of the detector')
      .nullable()
      .optional(),
  })
  .brand('@newswitch/detector_kube_state')
  .describe(
    'Data class representing metadata for a kube, including its ID and affine transformation matrix.',
  );
export type DetectorKubeState = z.input<typeof DetectorKubeStateSchema>;
export type DetectorKubeStateOutput = z.infer<typeof DetectorKubeStateSchema>;

export const FilterKubeStateSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/filter_kube_state')
      .default('@newswitch/filter_kube_state'),
    kube_id: z.string(),
    wavelength: z.number(),
    /** Affine transformation matrix of the kube */
    affine_matrix: z
      .array(z.array(z.number()))
      .describe('Affine transformation matrix of the kube'),
    /** Model name of the objective lens (e.g., 'Plan-Apochromat 63x/1.4 Oil DIC M27') */
    model_name: z
      .string()
      .describe(
        "Model name of the objective lens (e.g., 'Plan-Apochromat 63x/1.4 Oil DIC M27')",
      )
      .nullable()
      .optional(),
    /** Path to a file containing the physical model of the objective lens */
    model_file: z
      .string()
      .describe(
        'Path to a file containing the physical model of the objective lens',
      )
      .nullable()
      .optional(),
  })
  .brand('@newswitch/filter_kube_state')
  .describe(
    'Data class representing metadata for a kube, including its ID and affine transformation matrix.',
  );
export type FilterKubeState = z.input<typeof FilterKubeStateSchema>;
export type FilterKubeStateOutput = z.infer<typeof FilterKubeStateSchema>;

export const IlluminationKubeStateSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/illumination_kube_state')
      .default('@newswitch/illumination_kube_state'),
    kube_id: z.string(),
    slot_id: z.number(),
    intensity: z.number(),
    wavelength: z.number(),
    /** Affine transformation matrix of the kube */
    affine_matrix: z
      .array(z.array(z.number()))
      .describe('Affine transformation matrix of the kube'),
    /** Model name of the objective lens (e.g., 'Plan-Apochromat 63x/1.4 Oil DIC M27') */
    model_name: z
      .string()
      .describe(
        "Model name of the objective lens (e.g., 'Plan-Apochromat 63x/1.4 Oil DIC M27')",
      )
      .nullable()
      .optional(),
    /** Path to a file containing the physical model of the objective lens */
    model_file: z
      .string()
      .describe(
        'Path to a file containing the physical model of the objective lens',
      )
      .nullable()
      .optional(),
  })
  .brand('@newswitch/illumination_kube_state')
  .describe(
    'Data class representing metadata for a kube, including its ID and affine transformation matrix.',
  );
export type IlluminationKubeState = z.input<typeof IlluminationKubeStateSchema>;
export type IlluminationKubeStateOutput = z.infer<
  typeof IlluminationKubeStateSchema
>;

export const GenericKubeStateSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/generic_kube_state')
      .default('@newswitch/generic_kube_state'),
    kube_id: z.string(),
    other_metadata: z.record(z.string(), z.string()),
    /** Affine transformation matrix of the kube */
    affine_matrix: z
      .array(z.array(z.number()))
      .describe('Affine transformation matrix of the kube'),
    /** Model name of the stage (e.g., 'Stage 100x/0.8 NA') */
    model_name: z
      .string()
      .describe("Model name of the stage (e.g., 'Stage 100x/0.8 NA')")
      .nullable()
      .optional(),
    /** Path to a file containing the physical model of the stage */
    model_file: z
      .string()
      .describe('Path to a file containing the physical model of the stage')
      .nullable()
      .optional(),
  })
  .brand('@newswitch/generic_kube_state')
  .describe(
    'Data class representing metadata for a kube, including its ID and affine transformation matrix.',
  );
export type GenericKubeState = z.input<typeof GenericKubeStateSchema>;
export type GenericKubeStateOutput = z.infer<typeof GenericKubeStateSchema>;

export const StageKubeStateSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/stage_kube_state')
      .default('@newswitch/stage_kube_state'),
    kube_id: z.string(),
    /** Affine transformation matrix of the kube */
    affine_matrix: z
      .array(z.array(z.number()))
      .describe('Affine transformation matrix of the kube'),
    /** Model name of the stage (e.g., 'Stage 100x/0.8 NA') */
    model_name: z
      .string()
      .describe("Model name of the stage (e.g., 'Stage 100x/0.8 NA')")
      .nullable()
      .optional(),
    /** Path to a file containing the physical model of the stage */
    model_file: z
      .string()
      .describe('Path to a file containing the physical model of the stage')
      .nullable()
      .optional(),
  })
  .brand('@newswitch/stage_kube_state')
  .describe(
    'Data class representing metadata for a kube, including its ID and affine transformation matrix.',
  );
export type StageKubeState = z.input<typeof StageKubeStateSchema>;
export type StageKubeStateOutput = z.infer<typeof StageKubeStateSchema>;

export const DichroicKubeStateSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/dichroic_kube_state')
      .default('@newswitch/dichroic_kube_state'),
    kube_id: z.string(),
    /** Affine transformation matrix of the kube */
    affine_matrix: z
      .array(z.array(z.number()))
      .describe('Affine transformation matrix of the kube'),
    /** Model name of the dichroic mirror (e.g., 'Dichroic 405/488/561/640 nm') */
    model_name: z
      .string()
      .describe(
        "Model name of the dichroic mirror (e.g., 'Dichroic 405/488/561/640 nm')",
      )
      .nullable()
      .optional(),
    /** Path to a file containing the physical model of the dichroic mirror */
    model_file: z
      .string()
      .describe(
        'Path to a file containing the physical model of the dichroic mirror',
      )
      .nullable()
      .optional(),
  })
  .brand('@newswitch/dichroic_kube_state')
  .describe(
    'Data class representing metadata for a kube, including its ID and affine transformation matrix.',
  );
export type DichroicKubeState = z.input<typeof DichroicKubeStateSchema>;
export type DichroicKubeStateOutput = z.infer<typeof DichroicKubeStateSchema>;

export const FilterBankKubeStateSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/filter_bank_kube_state')
      .default('@newswitch/filter_bank_kube_state'),
    kube_id: z.string(),
    slot_id: z.number(),
    center_wavelength: z.number(),
    bandwidth: z.number(),
    transmission: z.number(),
    /** Affine transformation matrix of the kube */
    affine_matrix: z
      .array(z.array(z.number()))
      .describe('Affine transformation matrix of the kube'),
    /** Model name of the filter bank (e.g., 'Filter Bank 405/488/561/640 nm') */
    model_name: z
      .string()
      .describe(
        "Model name of the filter bank (e.g., 'Filter Bank 405/488/561/640 nm')",
      )
      .nullable()
      .optional(),
    /** Path to a file containing the physical model of the objective lens */
    model_file: z
      .string()
      .describe(
        'Path to a file containing the physical model of the objective lens',
      )
      .nullable()
      .optional(),
  })
  .brand('@newswitch/filter_bank_kube_state')
  .describe(
    'Data class representing metadata for a kube, including its ID and affine transformation matrix.',
  );
export type FilterBankKubeState = z.input<typeof FilterBankKubeStateSchema>;
export type FilterBankKubeStateOutput = z.infer<
  typeof FilterBankKubeStateSchema
>;

export const ObjectiveTurretKubeStateSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/objective_turret_kube_state')
      .default('@newswitch/objective_turret_kube_state'),
    kube_id: z.string(),
    slot: z.number(),
    magnification: z.number(),
    numerical_aperture: z.number(),
    /** Affine transformation matrix of the kube */
    affine_matrix: z
      .array(z.array(z.number()))
      .describe('Affine transformation matrix of the kube'),
    /** Model name of the objective turret (e.g., 'Objective Turret 40x/0.6 NA') */
    model_name: z
      .string()
      .describe(
        "Model name of the objective turret (e.g., 'Objective Turret 40x/0.6 NA')",
      )
      .nullable()
      .optional(),
    /** Path to a file containing the physical model of the objective turret */
    model_file: z
      .string()
      .describe(
        'Path to a file containing the physical model of the objective turret',
      )
      .nullable()
      .optional(),
  })
  .brand('@newswitch/objective_turret_kube_state')
  .describe(
    'Data class representing metadata for a kube, including its ID and affine transformation matrix.',
  );
export type ObjectiveTurretKubeState = z.input<
  typeof ObjectiveTurretKubeStateSchema
>;
export type ObjectiveTurretKubeStateOutput = z.infer<
  typeof ObjectiveTurretKubeStateSchema
>;

export const KubeUnionSchema = createIndexedUnion([
  ObjectiveKubeStateSchema.describe(
    'Data class representing metadata for a kube, including its ID and affine transformation matrix.',
  ),
  DetectorKubeStateSchema.describe(
    'Data class representing metadata for a kube, including its ID and affine transformation matrix.',
  ),
  FilterKubeStateSchema.describe(
    'Data class representing metadata for a kube, including its ID and affine transformation matrix.',
  ),
  IlluminationKubeStateSchema.describe(
    'Data class representing metadata for a kube, including its ID and affine transformation matrix.',
  ),
  GenericKubeStateSchema.describe(
    'Data class representing metadata for a kube, including its ID and affine transformation matrix.',
  ),
  StageKubeStateSchema.describe(
    'Data class representing metadata for a kube, including its ID and affine transformation matrix.',
  ),
  DichroicKubeStateSchema.describe(
    'Data class representing metadata for a kube, including its ID and affine transformation matrix.',
  ),
  FilterBankKubeStateSchema.describe(
    'Data class representing metadata for a kube, including its ID and affine transformation matrix.',
  ),
  ObjectiveTurretKubeStateSchema.describe(
    'Data class representing metadata for a kube, including its ID and affine transformation matrix.',
  ),
]);

export const LightEdgeStateSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/light_edge_state')
      .default('@newswitch/light_edge_state'),
    /** Source identifier (e.g., ID of LED or laser) */
    source: z.string().describe('Source identifier (e.g., ID of LED or laser)'),
    /** Target identifier (e.g., ID of sample or detector) */
    target: z
      .string()
      .describe('Target identifier (e.g., ID of sample or detector)'),
    /** Intensity of the light source (arbitrary units) */
    intensity: z
      .number()
      .describe('Intensity of the light source (arbitrary units)')
      .nullable()
      .optional(),
    /** Polarization state of the light (e.g., 'linear', 'circular') */
    polarization: z
      .string()
      .describe("Polarization state of the light (e.g., 'linear', 'circular')")
      .nullable()
      .optional(),
  })
  .brand('@newswitch/light_edge_state')
  .describe(
    'Data class representing the light path used for an image, including illumination settings.',
  );
export type LightEdgeState = z.input<typeof LightEdgeStateSchema>;
export type LightEdgeStateOutput = z.infer<typeof LightEdgeStateSchema>;

export const LightPathSnapshotSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/light_path_snapshot')
      .default('@newswitch/light_path_snapshot'),
    /** Hash of the optical setup of this image: the transformation hash, the active light sources and the filters */
    hash: z
      .string()
      .describe(
        'Hash of the optical setup of this image: the transformation hash, the active light sources and the filters',
      ),
    /** List of kubes representing the optical components in the light path (e.g., objective, detector) */
    kubes: z
      .array(KubeUnionSchema)
      .describe(
        'List of kubes representing the optical components in the light path (e.g., objective, detector)',
      ),
    /** List of edges representing the light path from source to sample */
    edges: z.array(
      LightEdgeStateSchema.describe(
        'Data class representing the light path used for an image, including illumination settings.',
      ),
    ),
    /** Hash of what the optics do to a pixel (detector, objective, their poses), which keys the calibration of this light path. Where the sample is, is not part of it */
    transformation_hash: z
      .string()
      .describe(
        'Hash of what the optics do to a pixel (detector, objective, their poses), which keys the calibration of this light path. Where the sample is, is not part of it',
      ),
  })
  .brand('@newswitch/light_path_snapshot')
  .describe(
    'Data class representing the light path used for an image, including illumination settings.',
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
    /** Data class representing the light path used for an image, including illumination settings. */
    light_state: LightPathSnapshotSchema.describe(
      'Data class representing the light path used for an image, including illumination settings.',
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
export const CaptureImageArgsSchema = z.object({});
export const CaptureImageReturnSchema = z.object({
  return0: z.array(
    FrameSchema.describe(
      'Represents a single 3D volume captured by the detector.',
    ),
  ),
});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type CaptureImageArgs = z.input<typeof CaptureImageArgsSchema>;
export type CaptureImageReturn = z.infer<typeof CaptureImageReturnSchema>;

// --- Definition ---
export const CaptureImageDefinition: ActionDefinition<
  CaptureImageArgs,
  CaptureImageReturn
> = {
  name: 'capture_image',
  appKey: 'default',
  description: 'Capture an image from the detector and save it to disk.',
  argsSchema: CaptureImageArgsSchema,
  returnSchema: CaptureImageReturnSchema,
  lockKeys: ['camera_parameters', 'expanse_state', 'io'],
};

/**
 * Capture an image from the detector and save it to disk.
 */
export const useCaptureImage = () => {
  return useAction(CaptureImageDefinition);
};
