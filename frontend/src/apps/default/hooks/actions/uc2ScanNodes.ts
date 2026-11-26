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
export const Uc2ScanNodesArgsSchema = z.object({
  /** The board. */
  board: z.string().describe('The board.'),
  /** How long to listen for nodes, in seconds. */
  timeout: z
    .number()
    .describe('How long to listen for nodes, in seconds.')
    .nullable()
    .optional(),
});
export const Uc2ScanNodesReturnSchema = z.object({
  return0: z.array(
    Uc2NodeSchema.describe(
      "A board on the UC2 bus, as it says of itself: the board on the port, or a CAN node.\n\n    What it reports is the firmware's: ``image`` is the file it was flashed from\n    (``esp32_UC2_canopen_slave_motor_release_motX.bin``), ``firmware`` its version. ``wanted`` and\n    ``wanted_version`` are what the description pins it to (`newswitch.instrument.hardware.Firmware`).\n    ",
    ),
  ),
});

// --- Types ---
// Args is the INPUT type (what you construct and pass to the hook; useAction parses it).
// Return is the OUTPUT type (what comes back, already parsed).
export type Uc2ScanNodesArgs = z.input<typeof Uc2ScanNodesArgsSchema>;
export type Uc2ScanNodesReturn = z.infer<typeof Uc2ScanNodesReturnSchema>;

// --- Definition ---
export const Uc2ScanNodesDefinition: ActionDefinition<
  Uc2ScanNodesArgs,
  Uc2ScanNodesReturn
> = {
  name: 'uc2_scan_nodes',
  appKey: 'default',
  description:
    "What is on a board's bus: the CAN nodes, each with the image and version it runs (and the\n\nenv the description wants). The board on the port and the nodes also land in UC2State.",
  argsSchema: Uc2ScanNodesArgsSchema,
  returnSchema: Uc2ScanNodesReturnSchema,
  lockKeys: [],
};

/**
 * What is on a board's bus: the CAN nodes, each with the image and version it runs (and the

env the description wants). The board on the port and the nodes also land in UC2State.
 */
export const useUc2ScanNodes = () => {
  return useAction(Uc2ScanNodesDefinition);
};
