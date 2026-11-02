import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';
import { createIndexedUnion } from './utils';
import { validatorAccepts, type UtilCall } from '@/lib/arkitekt/calls';

// --- Shared Models ---
export const AcquisitionChannelSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/acquisition_channel')
      .default('@newswitch/acquisition_channel'),
    /** The detectors that image it, by name; each becomes channels of the dataset. */
    detectors: z
      .array(z.string())
      .describe(
        'The detectors that image it, by name; each becomes channels of the dataset.',
      ),
    /** What it shows (e.g., 'GFP'): the start of its channels' labels. */
    name: z
      .string()
      .describe(
        "What it shows (e.g., 'GFP'): the start of its channels' labels.",
      ),
    /** What to set for it, by variable (e.g., 'laser_488.power', 'filter.slot'). A source it does not name is off. */
    set_to: z
      .record(z.string(), z.number())
      .describe(
        "What to set for it, by variable (e.g., 'laser_488.power', 'filter.slot'). A source it does not name is off.",
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
          message: 'We need at least one detector to acquire this channel',
          path: ['detectors'],
        });
      }
    }
  })
  .brand('@newswitch/acquisition_channel')
  .describe(
    'One thing to see: what to set for it, and the detectors that take an image of it.',
  );
export type AcquisitionChannel = z.input<typeof AcquisitionChannelSchema>;
export type AcquisitionChannelOutput = z.infer<typeof AcquisitionChannelSchema>;

export const PositionSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/position')
      .default('@newswitch/position'),
    system: z.string(),
    coordinates: z.record(z.string(), z.number()),
  })
  .brand('@newswitch/position')
  .describe(
    'Where to look: a place in the sample, an image, a well; nothing: stay.',
  );
export type Position = z.input<typeof PositionSchema>;
export type PositionOutput = z.infer<typeof PositionSchema>;

export const AcquisitionPositionSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/acquisition_position')
      .default('@newswitch/acquisition_position'),
    /** Where to look: a place in the sample, an image, a well; nothing: stay. */
    at: PositionSchema.describe(
      'Where to look: a place in the sample, an image, a well; nothing: stay.',
    )
      .nullable()
      .optional(),
    /** What else to set there, by variable (e.g., 'objective.slot'). */
    set_to: z
      .record(z.string(), z.number())
      .describe(
        "What else to set there, by variable (e.g., 'objective.slot').",
      ),
    /** What to call it. */
    name: z.string().describe('What to call it.'),
  })
  .brand('@newswitch/acquisition_position')
  .describe('One place to go: each is a dataset of its own.');
export type AcquisitionPosition = z.input<typeof AcquisitionPositionSchema>;
export type AcquisitionPositionOutput = z.infer<
  typeof AcquisitionPositionSchema
>;

export const AcquisitionStackSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/acquisition_stack')
      .default('@newswitch/acquisition_stack'),
    /** Where the planes are, from where the position is; none: one plane, there. */
    offsets: z
      .array(z.number())
      .describe(
        'Where the planes are, from where the position is; none: one plane, there.',
      ),
    /** What to sweep; by default what focuses, if it is clear which that is. */
    variable: z
      .string()
      .describe(
        'What to sweep; by default what focuses, if it is clear which that is.',
      )
      .nullable()
      .optional(),
  })
  .brand('@newswitch/acquisition_stack')
  .describe('Which planes to take at each position.');
export type AcquisitionStack = z.input<typeof AcquisitionStackSchema>;
export type AcquisitionStackOutput = z.infer<typeof AcquisitionStackSchema>;

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

export const MHookUnionSchema = createIndexedUnion([
  SoftwareAutofocusHookSchema.describe(
    'Refocus by software: sweep Z around the current position, move to the sharpest plane.',
  ),
  ZCalibrationHookSchema.describe(
    'Data class representing a z-calibration hook to be executed during acquisition.',
  ),
]);

export const THookUnionSchema = createIndexedUnion([
  SoftwareAutofocusHookSchema.describe(
    'Refocus by software: sweep Z around the current position, move to the sharpest plane.',
  ),
  ZCalibrationHookSchema.describe(
    'Data class representing a z-calibration hook to be executed during acquisition.',
  ),
]);

export const PHookUnionSchema = createIndexedUnion([
  SoftwareAutofocusHookSchema.describe(
    'Refocus by software: sweep Z around the current position, move to the sharpest plane.',
  ),
  ZCalibrationHookSchema.describe(
    'Data class representing a z-calibration hook to be executed during acquisition.',
  ),
]);

export const ZHookUnionSchema = createIndexedUnion([
  SoftwareAutofocusHookSchema.describe(
    'Refocus by software: sweep Z around the current position, move to the sharpest plane.',
  ),
  ZCalibrationHookSchema.describe(
    'Data class representing a z-calibration hook to be executed during acquisition.',
  ),
]);

export const AcquisitionPlanSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/acquisition_plan')
      .default('@newswitch/acquisition_plan'),
    /** What to see at each plane. */
    channels: z.array(
      AcquisitionChannelSchema.describe(
        'One thing to see: what to set for it, and the detectors that take an image of it.',
      ),
    ),
    /** Where to go; each is a dataset of its own. */
    positions: z.array(
      AcquisitionPositionSchema.describe(
        'One place to go: each is a dataset of its own.',
      ),
    ),
    /** Which planes to take at each position. */
    stack: AcquisitionStackSchema.describe(
      'Which planes to take at each position.',
    ),
    /** How many times to do all of it. */
    times: z.number().describe('How many times to do all of it.'),
    /** Seconds from the start of one time to the next; 0: right after it. */
    every_s: z
      .number()
      .describe(
        'Seconds from the start of one time to the next; 0: right after it.',
      ),
    /** In which order to visit the positions. */
    order: z.union([
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
    /** Name of the datasets; with several positions, each gets its position's. */
    name: z
      .string()
      .describe(
        "Name of the datasets; with several positions, each gets its position's.",
      ),
    /** What to run at the start (e.g., an autofocus). */
    m_hooks: z
      .array(MHookUnionSchema)
      .describe('What to run at the start (e.g., an autofocus).'),
    /** What to run each time. */
    t_hooks: z.array(THookUnionSchema).describe('What to run each time.'),
    /** What to run at each position, on arrival. */
    p_hooks: z
      .array(PHookUnionSchema)
      .describe('What to run at each position, on arrival.'),
    /** What to run at each plane. */
    z_hooks: z.array(ZHookUnionSchema).describe('What to run at each plane.'),
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
      const scope = { value: val['channels'], dependencies: {} };

      if (!validatorAccepts(call, scope)) {
        ctx.addIssue({
          code: 'custom',
          message: 'You need at least one channel to perform an acquisition',
          path: ['channels'],
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
      const scope = { value: val['positions'], dependencies: {} };

      if (!validatorAccepts(call, scope)) {
        ctx.addIssue({
          code: 'custom',
          message: 'You need at least one position to perform an acquisition',
          path: ['positions'],
        });
      }
    }
  })
  .brand('@newswitch/acquisition_plan')
  .describe(
    'What to acquire: every channel, on every plane, at every position, every time.',
  );
export type AcquisitionPlan = z.input<typeof AcquisitionPlanSchema>;
export type AcquisitionPlanOutput = z.infer<typeof AcquisitionPlanSchema>;

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
    /** Which detector's record it is */
    detector: z.string().describe("Which detector's record it is"),
  })
  .brand('@newswitch/acquired_dataset')
  .describe('A dataset an acquisition created, in the store it went to.');
export type AcquiredDataset = z.input<typeof AcquiredDatasetSchema>;
export type AcquiredDatasetOutput = z.infer<typeof AcquiredDatasetSchema>;

// --- Schemas ---
export const AcquireArgsSchema = z.object({
  /** What to acquire: every channel, on every plane, at every position, every time. */
  plan: AcquisitionPlanSchema.describe(
    'What to acquire: every channel, on every plane, at every position, every time.',
  ),
});
export const AcquireReturnSchema = z.object({
  /** The datasets created: for each position, one per detector, in the order the plan names
them. */
  return0: z.array(
    AcquiredDatasetSchema.describe(
      'A dataset an acquisition created, in the store it went to.',
    ),
  ),
});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type AcquireArgs = z.input<typeof AcquireArgsSchema>;
export type AcquireReturn = z.infer<typeof AcquireReturnSchema>;

// --- Definition ---
export const AcquireDefinition: ActionDefinition<AcquireArgs, AcquireReturn> = {
  name: 'acquire',
  appKey: 'default',
  description:
    'Acquire times x positions x planes x channels, into a record per position and detector.\n\nEach time it visits each position, then each plane of the stack, and every channel sets what it\nsets and its detectors take their images; hooks run at the start (`m_hooks`), each time\n(`t_hooks`), at each position (`p_hooks`) and at each plane (`z_hooks`).',
  argsSchema: AcquireArgsSchema,
  returnSchema: AcquireReturnSchema,
  lockKeys: ['detector', 'motion', 'swap', 'tune'],
};

/**
 * Acquire times x positions x planes x channels, into a record per position and detector.

Each time it visits each position, then each plane of the stack, and every channel sets what it
sets and its detectors take their images; hooks run at the start (`m_hooks`), each time
(`t_hooks`), at each position (`p_hooks`) and at each plane (`z_hooks`).
 */
export const useAcquire = () => {
  return useAction(AcquireDefinition);
};
