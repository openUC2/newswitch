import { z } from 'zod';
import { buildUseState, type StateDefinition } from '@/lib/arkitekt/state';
import { createIndexedUnion } from './utils';

// --- Sub-Schemas ---
export const ObjectiveKubeSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/objective_kube')
      .default('@newswitch/objective_kube'),
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
  .brand('@newswitch/objective_kube')
  .describe(
    'Data class representing metadata for a kube, including its ID and affine transformation matrix.',
  );
export type ObjectiveKube = z.input<typeof ObjectiveKubeSchema>;
export type ObjectiveKubeOutput = z.infer<typeof ObjectiveKubeSchema>;

export const DetectorKubeSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/detector_kube')
      .default('@newswitch/detector_kube'),
    kube_id: z.string(),
    slot_id: z.number(),
    /** Affine transformation matrix of the kube */
    affine_matrix: z
      .array(z.array(z.number()))
      .describe('Affine transformation matrix of the kube'),
    /** Model name of the detector (e.g., 'Plan-Apochromat 63x/1.4 Oil DIC M27') */
    model_name: z
      .string()
      .describe(
        "Model name of the detector (e.g., 'Plan-Apochromat 63x/1.4 Oil DIC M27')",
      )
      .nullable()
      .optional(),
    /** Path to a file containing the physical model of the detector */
    model_file: z
      .string()
      .describe('Path to a file containing the physical model of the detector')
      .nullable()
      .optional(),
  })
  .brand('@newswitch/detector_kube')
  .describe(
    'Data class representing metadata for a kube, including its ID and affine transformation matrix.',
  );
export type DetectorKube = z.input<typeof DetectorKubeSchema>;
export type DetectorKubeOutput = z.infer<typeof DetectorKubeSchema>;

export const FilterKubeSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/filter_kube')
      .default('@newswitch/filter_kube'),
    kube_id: z.string(),
    wavelength: z.number(),
    /** Affine transformation matrix of the kube */
    affine_matrix: z
      .array(z.array(z.number()))
      .describe('Affine transformation matrix of the kube'),
    /** Model name of the filter (e.g., 'Plan-Apochromat 63x/1.4 Oil DIC M27') */
    model_name: z
      .string()
      .describe(
        "Model name of the filter (e.g., 'Plan-Apochromat 63x/1.4 Oil DIC M27')",
      )
      .nullable()
      .optional(),
    /** Path to a file containing the physical model of the filter */
    model_file: z
      .string()
      .describe('Path to a file containing the physical model of the filter')
      .nullable()
      .optional(),
  })
  .brand('@newswitch/filter_kube')
  .describe(
    'Data class representing metadata for a kube, including its ID and affine transformation matrix.',
  );
export type FilterKube = z.input<typeof FilterKubeSchema>;
export type FilterKubeOutput = z.infer<typeof FilterKubeSchema>;

export const IlluminationKubeSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/illumination_kube')
      .default('@newswitch/illumination_kube'),
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
  .brand('@newswitch/illumination_kube')
  .describe(
    'Data class representing metadata for a kube, including its ID and affine transformation matrix.',
  );
export type IlluminationKube = z.input<typeof IlluminationKubeSchema>;
export type IlluminationKubeOutput = z.infer<typeof IlluminationKubeSchema>;

export const GenericKubeSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/generic_kube')
      .default('@newswitch/generic_kube'),
    kube_id: z.string(),
    other_metadata: z.record(z.string(), z.string()),
    /** Affine transformation matrix of the kube */
    affine_matrix: z
      .array(z.array(z.number()))
      .describe('Affine transformation matrix of the kube'),
    /** Model name of the generic kube (e.g., 'Plan-Apochromat 63x/1.4 Oil DIC M27') */
    model_name: z
      .string()
      .describe(
        "Model name of the generic kube (e.g., 'Plan-Apochromat 63x/1.4 Oil DIC M27')",
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
    /** Name of the state accessor method to get the current state of this kube (e.g., 'detector_state.affine_matrix') */
    state_accessor: z
      .string()
      .describe(
        "Name of the state accessor method to get the current state of this kube (e.g., 'detector_state.affine_matrix')",
      )
      .nullable()
      .optional(),
  })
  .brand('@newswitch/generic_kube')
  .describe(
    'Data class representing metadata for a kube, including its ID and affine transformation matrix.',
  );
export type GenericKube = z.input<typeof GenericKubeSchema>;
export type GenericKubeOutput = z.infer<typeof GenericKubeSchema>;

export const StageKubeSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/stage_kube')
      .default('@newswitch/stage_kube'),
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
  .brand('@newswitch/stage_kube')
  .describe(
    'Data class repesentating the stage, including its ID and affine transformation matrix.',
  );
export type StageKube = z.input<typeof StageKubeSchema>;
export type StageKubeOutput = z.infer<typeof StageKubeSchema>;

export const DichroicKubeSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/dichroic_kube')
      .default('@newswitch/dichroic_kube'),
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
  .brand('@newswitch/dichroic_kube')
  .describe(
    'Data class representing metadata for a kube, including its ID and affine transformation matrix.',
  );
export type DichroicKube = z.input<typeof DichroicKubeSchema>;
export type DichroicKubeOutput = z.infer<typeof DichroicKubeSchema>;

export const FilterBankKubeSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/filter_bank_kube')
      .default('@newswitch/filter_bank_kube'),
    kube_id: z.string(),
    /** Affine transformation matrix of the kube */
    affine_matrix: z
      .array(z.array(z.number()))
      .describe('Affine transformation matrix of the kube'),
    /** Model name of the filter bank (e.g., 'Plan-Apochromat 63x/1.4 Oil DIC M27') */
    model_name: z
      .string()
      .describe(
        "Model name of the filter bank (e.g., 'Plan-Apochromat 63x/1.4 Oil DIC M27')",
      )
      .nullable()
      .optional(),
    /** Path to a file containing the physical model of the filter bank */
    model_file: z
      .string()
      .describe(
        'Path to a file containing the physical model of the filter bank',
      )
      .nullable()
      .optional(),
  })
  .brand('@newswitch/filter_bank_kube')
  .describe(
    'Data class representing metadata for a kube, including its ID and affine transformation matrix.',
  );
export type FilterBankKube = z.input<typeof FilterBankKubeSchema>;
export type FilterBankKubeOutput = z.infer<typeof FilterBankKubeSchema>;

export const ObjectiveTurretKubeSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/objective_turret_kube')
      .default('@newswitch/objective_turret_kube'),
    kube_id: z.string(),
    /** Affine transformation matrix of the kube */
    affine_matrix: z
      .array(z.array(z.number()))
      .describe('Affine transformation matrix of the kube'),
    /** Model name of the objective turret (e.g., 'Plan-Apochromat 63x/1.4 Oil DIC M27') */
    model_name: z
      .string()
      .describe(
        "Model name of the objective turret (e.g., 'Plan-Apochromat 63x/1.4 Oil DIC M27')",
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
  .brand('@newswitch/objective_turret_kube')
  .describe(
    'Data class representing metadata for a kube, including its ID and affine transformation matrix.',
  );
export type ObjectiveTurretKube = z.input<typeof ObjectiveTurretKubeSchema>;
export type ObjectiveTurretKubeOutput = z.infer<
  typeof ObjectiveTurretKubeSchema
>;

export const KubeUnionSchema = createIndexedUnion([
  ObjectiveKubeSchema.describe(
    'Data class representing metadata for a kube, including its ID and affine transformation matrix.',
  ),
  DetectorKubeSchema.describe(
    'Data class representing metadata for a kube, including its ID and affine transformation matrix.',
  ),
  FilterKubeSchema.describe(
    'Data class representing metadata for a kube, including its ID and affine transformation matrix.',
  ),
  IlluminationKubeSchema.describe(
    'Data class representing metadata for a kube, including its ID and affine transformation matrix.',
  ),
  GenericKubeSchema.describe(
    'Data class representing metadata for a kube, including its ID and affine transformation matrix.',
  ),
  StageKubeSchema.describe(
    'Data class repesentating the stage, including its ID and affine transformation matrix.',
  ),
  DichroicKubeSchema.describe(
    'Data class representing metadata for a kube, including its ID and affine transformation matrix.',
  ),
  FilterBankKubeSchema.describe(
    'Data class representing metadata for a kube, including its ID and affine transformation matrix.',
  ),
  ObjectiveTurretKubeSchema.describe(
    'Data class representing metadata for a kube, including its ID and affine transformation matrix.',
  ),
]);

export const LightEdgeSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/light_edge')
      .default('@newswitch/light_edge'),
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
  })
  .brand('@newswitch/light_edge')
  .describe(
    'Data class representing the light path used for an image, including illumination settings.',
  );
export type LightEdge = z.input<typeof LightEdgeSchema>;
export type LightEdgeOutput = z.infer<typeof LightEdgeSchema>;

export const LightPathSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/light_path')
      .default('@newswitch/light_path'),
    /** Slot number of the detector in the current light path configuration, used to determine which detector's metadata to include in the light path state */
    detector: z
      .number()
      .describe(
        "Slot number of the detector in the current light path configuration, used to determine which detector's metadata to include in the light path state",
      ),
    /** List of kubes representing the optical components in the light path (e.g., objective, detector) */
    kubes: z
      .array(KubeUnionSchema)
      .describe(
        'List of kubes representing the optical components in the light path (e.g., objective, detector)',
      ),
    /** List of edges representing the light path from source to sample */
    edges: z.array(
      LightEdgeSchema.describe(
        'Data class representing the light path used for an image, including illumination settings.',
      ),
    ),
  })
  .brand('@newswitch/light_path')
  .describe(
    'Data class representing the light path used for an image, including illumination settings.',
  );
export type LightPath = z.input<typeof LightPathSchema>;
export type LightPathOutput = z.infer<typeof LightPathSchema>;

// --- Main Schema ---
export const LightPathStateSchema = z.object({
  light_paths: z.array(
    LightPathSchema.describe(
      'Data class representing the light path used for an image, including illumination settings.',
    ),
  ),
  current_light_path: LightPathSchema.describe(
    'Data class representing the light path used for an image, including illumination settings.',
  )
    .nullable()
    .optional(),
});

// --- Type ---
export type LightPathState = z.infer<typeof LightPathStateSchema>;

// --- Definition ---
export const LightPathStateDefinition: StateDefinition<
  LightPathState,
  'LightPathState'
> = {
  appKey: 'default',
  key: 'LightPathState',
  schema: LightPathStateSchema,
};

/**
 * Hook to sync LightPathState
 */
export const useLightPathState = buildUseState<LightPathState>(
  LightPathStateDefinition,
);
