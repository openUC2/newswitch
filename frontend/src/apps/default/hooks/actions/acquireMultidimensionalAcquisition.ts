import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';
import { createIndexedUnion } from './utils';
import { validatorAccepts, type UtilCall } from '@/lib/arkitekt/calls';

// --- Shared Models ---
export const StreamIlluminationSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/stream_illumination')
      .default('@newswitch/stream_illumination'),
    source: z.string(),
    wavelength: z.number(),
    intensity: z.number(),
  })
  .brand('@newswitch/stream_illumination')
  .describe('Represents an illumination channel to acquire.');
export type StreamIllumination = z.input<typeof StreamIlluminationSchema>;
export type StreamIlluminationOutput = z.infer<typeof StreamIlluminationSchema>;

export const StreamsSchema = z
  .object({
    __identifier: z.literal('@newswitch/streams').default('@newswitch/streams'),
    /** The detectors that image this stream, by name or slot; each becomes a channel, a color camera one per color */
    detectors: z
      .array(z.string())
      .describe(
        'The detectors that image this stream, by name or slot; each becomes a channel, a color camera one per color',
      ),
    /** What this stream shows (e.g., 'GFP', 'RFP'): the start of its channels' labels */
    mapping: z
      .string()
      .describe(
        "What this stream shows (e.g., 'GFP', 'RFP'): the start of its channels' labels",
      ),
    /** List of illuminations to use for this stream (e.g., [{'source': 'LED1', 'wavelength': 488, 'intensity': 0.8}]) */
    illuminations: z.array(
      StreamIlluminationSchema.describe(
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
      const scope = { value: val['detectors'], dependencies: {} };

      if (!validatorAccepts(call, scope)) {
        ctx.addIssue({
          code: 'custom',
          message: 'We need at least one detector to acquire this stream',
          path: ['detectors'],
        });
      }
    }

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
  .describe(
    'One lighting of the sample, and the detectors that take an image of it.',
  );
export type Streams = z.input<typeof StreamsSchema>;
export type StreamsOutput = z.infer<typeof StreamsSchema>;

export const SoftwareAutofocusHookSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/software_autofocus_hook')
      .default('@newswitch/software_autofocus_hook'),
    z_range: z.number().nullable().optional(),
    steps: z.number(),
  })
  .brand('@newswitch/software_autofocus_hook')
  .describe(
    'Refocus by software: sweep Z around the current position, move to the sharpest plane.',
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
    'Refocus by software: sweep Z around the current position, move to the sharpest plane.',
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
        'One lighting of the sample, and the detectors that take an image of it.',
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
    'Refocus by software: sweep Z around the current position, move to the sharpest plane.',
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
    'Refocus by software: sweep Z around the current position, move to the sharpest plane.',
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
    'Refocus by software: sweep Z around the current position, move to the sharpest plane.',
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
    /** Name of the datasets created (e.g., 'experiment1'); with several positions, each ends in its own P<n> */
    file_name: z
      .string()
      .describe(
        "Name of the datasets created (e.g., 'experiment1'); with several positions, each ends in its own P<n>",
      ),
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
  .describe('Configuration for a multidimensional acquisition.');
export type MultidimensionalAcquisition = z.input<
  typeof MultidimensionalAcquisitionSchema
>;
export type MultidimensionalAcquisitionOutput = z.infer<
  typeof MultidimensionalAcquisitionSchema
>;

export const AcquiredDatasetSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/acquired_dataset')
      .default('@newswitch/acquired_dataset'),
    id: z.string(),
    name: z.string(),
    /** Which position of the acquisition it holds, from 0 */
    position: z
      .number()
      .describe('Which position of the acquisition it holds, from 0'),
  })
  .brand('@newswitch/acquired_dataset')
  .describe('A dataset an acquisition created, in the store it went to.');
export type AcquiredDataset = z.input<typeof AcquiredDatasetSchema>;
export type AcquiredDatasetOutput = z.infer<typeof AcquiredDatasetSchema>;

// --- Schemas ---
export const AcquireMultidimensionalAcquisitionArgsSchema = z.object({
  /** Configuration for a multidimensional acquisition. */
  config: MultidimensionalAcquisitionSchema.describe(
    'Configuration for a multidimensional acquisition.',
  ),
});
export const AcquireMultidimensionalAcquisitionReturnSchema = z.object({
  /** The datasets created, one per position. */
  return0: z.array(
    AcquiredDatasetSchema.describe(
      'A dataset an acquisition created, in the store it went to.',
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
    'Acquire timepoints x positions x z planes x channels, into one dataset per position.\n\nPer timepoint the stage visits each position, then each plane of its stack, and every stream\nlights the sample for its detectors; hooks (`m_hooks`, `t_hooks`, `p_hooks`, `z_hooks`) run at\nthe start, per timepoint, per position and per plane.',
  argsSchema: AcquireMultidimensionalAcquisitionArgsSchema,
  returnSchema: AcquireMultidimensionalAcquisitionReturnSchema,
  lockKeys: [
    'camera_parameters',
    'hook_registry',
    'illumination',
    'stage_position',
  ],
};

/**
 * Acquire timepoints x positions x z planes x channels, into one dataset per position.

Per timepoint the stage visits each position, then each plane of its stack, and every stream
lights the sample for its detectors; hooks (`m_hooks`, `t_hooks`, `p_hooks`, `z_hooks`) run at
the start, per timepoint, per position and per plane.
 */
export const useAcquireMultidimensionalAcquisition = () => {
  return useAction(AcquireMultidimensionalAcquisitionDefinition);
};
