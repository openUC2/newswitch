import { z } from 'zod';
import { useAction, type ActionDefinition } from '@/lib/arkitekt/task';

// --- Shared Models ---
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

// --- Schemas ---
export const UpdateFirmwareArgsSchema = z.object({
  /** The board. */
  board: z.string().describe('The board.'),
  /** Only these CAN nodes (each needs an env in the description); default: all it names. */
  nodes: z
    .array(z.number())
    .describe(
      'Only these CAN nodes (each needs an env in the description); default: all it names.',
    )
    .nullable()
    .optional(),
  /** Flash the board on the port too. */
  port_board: z
    .boolean()
    .describe('Flash the board on the port too.')
    .nullable()
    .optional(),
  /** Write the board's merged image (bootloader and partitions), as for a blank board. It
resets what the board stored: its node id, role and positions. */
  full: z
    .boolean()
    .describe(
      "Write the board's merged image (bootloader and partitions), as for a blank board. It\nresets what the board stored: its node id, role and positions.",
    )
    .nullable()
    .optional(),
  /** Flash even what already runs the wanted image. */
  force: z
    .boolean()
    .describe('Flash even what already runs the wanted image.')
    .nullable()
    .optional(),
});
export const UpdateFirmwareReturnSchema = z.object({
  return0: z.array(
    Uc2NodeSchema.describe(
      "A board on the UC2 bus, as it says of itself: the board on the port, or a CAN node.\n\n    What it reports is the firmware's: ``image`` is the file it was flashed from\n    (``esp32_UC2_canopen_slave_motor_release_motX.bin``), ``firmware`` its version. ``wanted`` and\n    ``wanted_version`` are what the description pins it to (`newswitch.instrument.hardware.Firmware`).\n    ",
    ),
  ),
});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type UpdateFirmwareArgs = z.input<typeof UpdateFirmwareArgsSchema>;
export type UpdateFirmwareReturn = z.infer<typeof UpdateFirmwareReturnSchema>;

// --- Definition ---
export const UpdateFirmwareDefinition: ActionDefinition<
  UpdateFirmwareArgs,
  UpdateFirmwareReturn
> = {
  name: 'update_firmware',
  appKey: 'default',
  description:
    'Flash the firmware the description names (``boards.<board>.firmware``) where it is not\n\nrunning yet: the board on the port over USB first, then each CAN node through the bus. A\nflashed board counts once it reports its new image. The bus is down meanwhile.',
  argsSchema: UpdateFirmwareArgsSchema,
  returnSchema: UpdateFirmwareReturnSchema,
  lockKeys: ['galvo', 'motion', 'swap', 'tune'],
};

/**
 * Flash the firmware the description names (``boards.<board>.firmware``) where it is not

running yet: the board on the port over USB first, then each CAN node through the bus. A
flashed board counts once it reports its new image. The bus is down meanwhile.
 */
export const useUpdateFirmware = () => {
  return useAction(UpdateFirmwareDefinition);
};
