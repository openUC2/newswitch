import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';
import { createIndexedUnion } from './utils';
import { validatorAccepts, type UtilCall } from '@/lib/arkitekt/calls';

// --- Shared Models ---
export const IlluminationSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/illumination')
      .default('@newswitch/illumination'),
    source: z.string(),
    wavelength: z.number(),
    intensity: z.number(),
  })
  .brand('@newswitch/illumination')
  .describe('Represents an illumination channel to acquire.');
export type Illumination = z.input<typeof IlluminationSchema>;
export type IlluminationOutput = z.infer<typeof IlluminationSchema>;

export const StreamsSchema = z
  .object({
    __identifier: z.literal('@newswitch/streams').default('@newswitch/streams'),
    /** Name or slot of the detector to use for this stream (e.g., 'Camera1' or '1') */
    detector: z
      .string()
      .describe(
        "Name or slot of the detector to use for this stream (e.g., 'Camera1' or '1')",
      ),
    /** Mapping name for this stream (e.g., 'GFP', 'RFP') to be used in file naming and metadata */
    mapping: z
      .string()
      .describe(
        "Mapping name for this stream (e.g., 'GFP', 'RFP') to be used in file naming and metadata",
      ),
    /** List of illuminations to use for this stream (e.g., [{'source': 'LED1', 'wavelength': 488, 'intensity': 0.8}]) */
    illuminations: z.array(
      IlluminationSchema.describe(
        'Represents an illumination channel to acquire.',
      ),
    ),
  })
  .superRefine((val, ctx) => {
    {
      // len(value) > 0
      const call = {
        operation: 'gt',
        arguments: [
          {
            key: 'a',
            valueLiteral: null,
            valuePath: null,
            agentCall: null,
            utilCall: {
              operation: 'len',
              arguments: [
                {
                  key: 'a',
                  valueLiteral: null,
                  valuePath: 'value',
                  agentCall: null,
                  utilCall: null,
                  valueList: null,
                  valueDict: null,
                },
              ],
            },
            valueList: null,
            valueDict: null,
          },
          {
            key: 'b',
            valueLiteral: 0,
            valuePath: null,
            agentCall: null,
            utilCall: null,
            valueList: null,
            valueDict: null,
          },
        ],
      } as UtilCall;
      const scope = { value: val['illuminations'], dependencies: {} };

      if (!validatorAccepts(call, scope)) {
        ctx.addIssue({
          code: 'custom',
          message:
            'We need at least one illumination channel to acquire this stream',
          path: ['illuminations'],
        });
      }
    }
  })
  .brand('@newswitch/streams')
  .describe('Represents which channels to acquire at each position.');
export type Streams = z.input<typeof StreamsSchema>;
export type StreamsOutput = z.infer<typeof StreamsSchema>;

export const SoftwareAutofocusHookSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/software_autofocus_hook')
      .default('@newswitch/software_autofocus_hook'),
    speed: z.number(),
  })
  .brand('@newswitch/software_autofocus_hook')
  .describe(
    'Data class representing a software autofocus hook to be executed during acquisition.',
  );
export type SoftwareAutofocusHook = z.input<typeof SoftwareAutofocusHookSchema>;
export type SoftwareAutofocusHookOutput = z.infer<
  typeof SoftwareAutofocusHookSchema
>;

export const ZCalibrationHookSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/z_calibration_hook')
      .default('@newswitch/z_calibration_hook'),
    calibration_points: z.number(),
  })
  .brand('@newswitch/z_calibration_hook')
  .describe(
    'Data class representing a z-calibration hook to be executed during acquisition.',
  );
export type ZCalibrationHook = z.input<typeof ZCalibrationHookSchema>;
export type ZCalibrationHookOutput = z.infer<typeof ZCalibrationHookSchema>;

export const ZHookUnionSchema = createIndexedUnion([
  SoftwareAutofocusHookSchema.describe(
    'Data class representing a software autofocus hook to be executed during acquisition.',
  ),
  ZCalibrationHookSchema.describe(
    'Data class representing a z-calibration hook to be executed during acquisition.',
  ),
]);

export const StackSchema = z
  .object({
    __identifier: z.literal('@newswitch/stack').default('@newswitch/stack'),
    z_offset: z.number(),
    z_slices: z.array(z.number()),
    z_step: z.number(),
    channels: z.array(
      StreamsSchema.describe(
        'Represents which channels to acquire at each position.',
      ),
    ),
    /** List of hooks to execute at each z-slice (e.g., 'autofocus', 'z_calibration') */
    z_hooks: z
      .array(ZHookUnionSchema)
      .describe(
        "List of hooks to execute at each z-slice (e.g., 'autofocus', 'z_calibration')",
      ),
  })
  .brand('@newswitch/stack')
  .describe('Represents a stack of images at different z-slices.');
export type Stack = z.input<typeof StackSchema>;
export type StackOutput = z.infer<typeof StackSchema>;

export const PHookUnionSchema = createIndexedUnion([
  SoftwareAutofocusHookSchema.describe(
    'Data class representing a software autofocus hook to be executed during acquisition.',
  ),
  ZCalibrationHookSchema.describe(
    'Data class representing a z-calibration hook to be executed during acquisition.',
  ),
]);

export const PositionSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/position')
      .default('@newswitch/position'),
    x: z.number(),
    y: z.number(),
    z: z.number(),
    stacks: z.array(
      StackSchema.describe(
        'Represents a stack of images at different z-slices.',
      ),
    ),
    /** List of hooks to execute at each position (e.g., 'autofocus', 'z_calibration') */
    p_hooks: z
      .array(PHookUnionSchema)
      .describe(
        "List of hooks to execute at each position (e.g., 'autofocus', 'z_calibration')",
      ),
  })
  .brand('@newswitch/position')
  .describe('Represents a position in 3D space.');
export type Position = z.input<typeof PositionSchema>;
export type PositionOutput = z.infer<typeof PositionSchema>;

export const THookUnionSchema = createIndexedUnion([
  SoftwareAutofocusHookSchema.describe(
    'Data class representing a software autofocus hook to be executed during acquisition.',
  ),
  ZCalibrationHookSchema.describe(
    'Data class representing a z-calibration hook to be executed during acquisition.',
  ),
]);

export const TimepointSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/timepoint')
      .default('@newswitch/timepoint'),
    /** Absolute time to acquire this timepoint (e.g., '2024-01-01T12:00:00') or None to acquire immediately after the previous timepoint */
    time: z
      .any()
      .describe(
        "Absolute time to acquire this timepoint (e.g., '2024-01-01T12:00:00') or None to acquire immediately after the previous timepoint",
      )
      .nullable()
      .optional(),
    /** List of stage positions to acquire at this timepoint */
    positions: z.array(
      PositionSchema.describe('Represents a position in 3D space.'),
    ),
    /** Order in which to visit stage positions (e.g., 'sequential', 'random') */
    position_order: z.union([
      z
        .literal('SEQUENTIAL')
        .describe(
          'Defines the order in which stage positions are visited during acquisition.',
        ),
      z
        .literal('RANDOM')
        .describe(
          'Defines the order in which stage positions are visited during acquisition.',
        ),
    ]),
    /** List of hooks to execute at each timepoint (e.g., 'autofocus', 'z_calibration') */
    t_hooks: z
      .array(THookUnionSchema)
      .describe(
        "List of hooks to execute at each timepoint (e.g., 'autofocus', 'z_calibration')",
      ),
  })
  .brand('@newswitch/timepoint')
  .describe('Represents a timepoint in a temporal sequence.');
export type Timepoint = z.input<typeof TimepointSchema>;
export type TimepointOutput = z.infer<typeof TimepointSchema>;

export const MHookUnionSchema = createIndexedUnion([
  SoftwareAutofocusHookSchema.describe(
    'Data class representing a software autofocus hook to be executed during acquisition.',
  ),
  ZCalibrationHookSchema.describe(
    'Data class representing a z-calibration hook to be executed during acquisition.',
  ),
]);

export const MultidimensionalAcquisitionSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/multidimensional_acquisition')
      .default('@newswitch/multidimensional_acquisition'),
    /** List of timepoints to acquire, each with its own stage positions and hooks */
    timepoints: z.array(
      TimepointSchema.describe(
        'Represents a timepoint in a temporal sequence.',
      ),
    ),
    /** Base file name for acquired images (e.g., 'experiment1') */
    file_name: z
      .string()
      .describe("Base file name for acquired images (e.g., 'experiment1')"),
    /** File format for saving acquired images (e.g., 'TIFF', 'PNG') */
    file_format: z
      .string()
      .describe("File format for saving acquired images (e.g., 'TIFF', 'PNG')"),
    /** List of hooks to execute at the start of the acquisition (e.g., 'autofocus', 'z_calibration') */
    m_hooks: z
      .array(MHookUnionSchema)
      .describe(
        "List of hooks to execute at the start of the acquisition (e.g., 'autofocus', 'z_calibration')",
      ),
  })
  .superRefine((val, ctx) => {
    {
      // len(value) > 0
      const call = {
        operation: 'gt',
        arguments: [
          {
            key: 'a',
            valueLiteral: null,
            valuePath: null,
            agentCall: null,
            utilCall: {
              operation: 'len',
              arguments: [
                {
                  key: 'a',
                  valueLiteral: null,
                  valuePath: 'value',
                  agentCall: null,
                  utilCall: null,
                  valueList: null,
                  valueDict: null,
                },
              ],
            },
            valueList: null,
            valueDict: null,
          },
          {
            key: 'b',
            valueLiteral: 0,
            valuePath: null,
            agentCall: null,
            utilCall: null,
            valueList: null,
            valueDict: null,
          },
        ],
      } as UtilCall;
      const scope = { value: val['timepoints'], dependencies: {} };

      if (!validatorAccepts(call, scope)) {
        ctx.addIssue({
          code: 'custom',
          message: 'You need at least one timepoint to perform an acquisition',
          path: ['timepoints'],
        });
      }
    }
  })
  .brand('@newswitch/multidimensional_acquisition')
  .describe('Configuration for the acquisition.');
export type MultidimensionalAcquisition = z.input<
  typeof MultidimensionalAcquisitionSchema
>;
export type MultidimensionalAcquisitionOutput = z.infer<
  typeof MultidimensionalAcquisitionSchema
>;

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

export const LightPathStateSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/light_path_state')
      .default('@newswitch/light_path_state'),
    /** Hash of the light path configuration, used to uniquely describe the optical path for this image */
    hash: z
      .string()
      .describe(
        'Hash of the light path configuration, used to uniquely describe the optical path for this image',
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
    /** Hash indicating if the kube is affecting the transformation from sample to pixel coordinates, which is used to determine if we can reuse the affine matrix from a previous image */
    transformation_hash: z
      .string()
      .describe(
        'Hash indicating if the kube is affecting the transformation from sample to pixel coordinates, which is used to determine if we can reuse the affine matrix from a previous image',
      ),
  })
  .brand('@newswitch/light_path_state')
  .describe(
    'Data class representing the light path used for an image, including illumination settings.',
  );
export type LightPathState = z.input<typeof LightPathStateSchema>;
export type LightPathStateOutput = z.infer<typeof LightPathStateSchema>;

export const MetadataSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/metadata')
      .default('@newswitch/metadata'),
    affine_matrix: z.array(z.array(z.number())),
    fov_width: z.number(),
    fov_height: z.number(),
    /** Data class representing the light path used for an image, including illumination settings. */
    light_state: LightPathStateSchema.describe(
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
export const AcquireMultidimensionalAcquisitionArgsSchema = z.object({
  /** Configuration for the acquisition. */
  config: MultidimensionalAcquisitionSchema.describe(
    'Configuration for the acquisition.',
  ),
});
export const AcquireMultidimensionalAcquisitionReturnSchema = z.object({
  /** List of acquired images with metadata. */
  return0: z.array(
    FrameSchema.describe(
      'Represents a single 3D volume captured by the detector.',
    ),
  ),
});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type AcquireMultidimensionalAcquisitionArgs = z.input<
  typeof AcquireMultidimensionalAcquisitionArgsSchema
>;
export type AcquireMultidimensionalAcquisitionReturn = z.infer<
  typeof AcquireMultidimensionalAcquisitionReturnSchema
>;

// --- Definition ---
export const AcquireMultidimensionalAcquisitionDefinition: ActionDefinition<
  AcquireMultidimensionalAcquisitionArgs,
  AcquireMultidimensionalAcquisitionReturn
> = {
  name: 'acquire_multidimensional_acquisition',
  appKey: 'default',
  description:
    'Simulate the acquisition of a multidimensional dataset based on the provided configuration.',
  argsSchema: AcquireMultidimensionalAcquisitionArgsSchema,
  returnSchema: AcquireMultidimensionalAcquisitionReturnSchema,
  lockKeys: [
    'camera_parameters',
    'expanse_state',
    'hook_registry',
    'illumination',
    'io',
    'stage_position',
  ],
};

/**
 * Simulate the acquisition of a multidimensional dataset based on the provided configuration.
 */
export const useAcquireMultidimensionalAcquisition = () => {
  return useAction(AcquireMultidimensionalAcquisitionDefinition);
};
