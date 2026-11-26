import { z } from 'zod';
import { buildUseState, type StateDefinition } from '@/lib/arkitekt/state';

// --- Sub-Schemas ---
export const Uc2NodeSchema = z
  .object({
    __identifier: z
      .literal('@newswitch/uc2_node')
      .default('@newswitch/uc2_node'),
    can_id: z.number(),
    kind: z.string(),
    status: z.string(),
    firmware: z.string(),
    image: z.string(),
    build: z.string(),
    mac: z.string(),
    wanted: z.string().nullable().optional(),
    wanted_version: z.string().nullable().optional(),
  })
  .brand('@newswitch/uc2_node')
  .describe(
    "A board on the UC2 bus, as it says of itself: the board on the port, or a CAN node.\n\n    What it reports is the firmware's: ``image`` is the file it was flashed from\n    (``esp32_UC2_canopen_slave_motor_release_motX.bin``), ``firmware`` its version. ``wanted`` and\n    ``wanted_version`` are what the description pins it to (`newswitch.instrument.hardware.Firmware`).\n    ",
  );
export type Uc2Node = z.input<typeof Uc2NodeSchema>;
export type Uc2NodeOutput = z.infer<typeof Uc2NodeSchema>;

// --- Main Schema ---
export const Uc2StateSchema = z.object({
  boards: z.array(z.string()),
  connected: z.boolean(),
  transport: z.string(),
  firmware: z.string(),
  estop_active: z.boolean(),
  nodes_online: z.array(z.number()),
  last_error: z.string(),
  board: Uc2NodeSchema.describe(
    "A board on the UC2 bus, as it says of itself: the board on the port, or a CAN node.\n\n    What it reports is the firmware's: ``image`` is the file it was flashed from\n    (``esp32_UC2_canopen_slave_motor_release_motX.bin``), ``firmware`` its version. ``wanted`` and\n    ``wanted_version`` are what the description pins it to (`newswitch.instrument.hardware.Firmware`).\n    ",
  )
    .nullable()
    .optional(),
  nodes: z.array(
    Uc2NodeSchema.describe(
      "A board on the UC2 bus, as it says of itself: the board on the port, or a CAN node.\n\n    What it reports is the firmware's: ``image`` is the file it was flashed from\n    (``esp32_UC2_canopen_slave_motor_release_motX.bin``), ``firmware`` its version. ``wanted`` and\n    ``wanted_version`` are what the description pins it to (`newswitch.instrument.hardware.Firmware`).\n    ",
    ),
  ),
  flashing: z.string().nullable().optional(),
});

// --- Type ---
export type Uc2State = z.infer<typeof Uc2StateSchema>;

// --- Definition ---
export const Uc2StateDefinition: StateDefinition<Uc2State, 'uc2'> = {
  appKey: 'default',
  key: 'uc2',
  schema: Uc2StateSchema,
};

/**
 * Hook to sync uc2
 */
export const useUc2State = buildUseState<Uc2State>(Uc2StateDefinition);
