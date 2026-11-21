"""What uc2canopen cannot do on a CAN bus: read a node's identity strings, and update its firmware.

uc2canopen speaks expedited SDO alone (values of at most 4 bytes). A node's identity is longer
(VSTRINGs: its firmware version at 0x2500, the image it was flashed from at 0x2501, its build at
0x2508, its MAC at 0x2509) and its firmware a DOMAIN (0x2F00), so both go through python-canopen's
segmented SDO, on the bus uc2canopen already has open: `attach` adds a python-canopen network to its
notifier, which then hears the replies too, and `detach` takes it off again.

Updating a node is the firmware's OTA (uc2-esp32 ``tools/canopen/uc2_ota_can.py``): CRC-32 to 0x2F02,
the size to 0x2F01 (which starts it), the image to 0x2F00, then 0x2F03 says whether it is complete
(3) or failed (0xFF, why at 0x2F05). The node then reboots into it. Blocking: run off the loop.
"""

from __future__ import annotations

import logging
import struct
import time
import zlib
from collections.abc import Callable
from typing import Any, Optional

logger = logging.getLogger(__name__)

FIRMWARE_VERSION = 0x2500
BOARD_IMAGE = 0x2501
BUILD_TIMESTAMP = 0x2508
MAC_ADDRESS = 0x2509
OTA_DATA = 0x2F00
OTA_SIZE = 0x2F01
OTA_CRC32 = 0x2F02
OTA_STATUS = 0x2F03
OTA_ERROR = 0x2F05
OTA_COMPLETE = 0x03
OTA_FAILED = 0xFF
#: Why an OTA failed (0x2F05).
OTA_ERRORS = {
    1: "no OTA partition",
    2: "could not begin",
    3: "write failed",
    4: "CRC mismatch",
    5: "commit failed",
    6: "size 0",
    7: "image too large",
}
#: The largest image a node takes (0x2F01).
OTA_MAX_SIZE = 0x140000


class Attached:
    """A python-canopen network on a bus another notifier reads."""

    def __init__(self, bus: Any, notifier: Any, response_timeout: float = 2.0) -> None:  # noqa: ANN401
        """Listen on `notifier` for what reaches `bus`, and send on it."""
        import canopen
        from canopen.network import MessageListener

        self.network = canopen.Network()
        self.network.bus = bus
        self._notifier = notifier
        self._listener = MessageListener(self.network)
        notifier.add_listener(self._listener)
        self._timeout = response_timeout

    def node(self, node_id: int) -> Any:  # noqa: ANN401 - a canopen.RemoteNode
        """The node `node_id`, with no object dictionary: addressed by index."""
        import canopen
        from canopen.sdo.client import SdoClient

        node = self.network.nodes.get(node_id) or self.network.add_node(
            node_id, canopen.ObjectDictionary()
        )
        assert isinstance(node.sdo, SdoClient)  # a remote node's
        node.sdo.RESPONSE_TIMEOUT = self._timeout
        return node

    def detach(self) -> None:
        """Take the network off the notifier again."""
        self._notifier.remove_listener(self._listener)


def attach(client: Any, response_timeout: float = 2.0) -> Attached:  # noqa: ANN401 - uc2canopen.UC2Client
    """A python-canopen network on the bus and notifier of a uc2canopen client."""
    return Attached(client._bus, client._notifier, response_timeout)


def _string(node: Any, index: int) -> str:  # noqa: ANN401
    try:
        return node.sdo.upload(index, 0).split(b"\0", 1)[0].decode(errors="replace").strip()
    except Exception as exc:  # an older firmware has no such entry  # noqa: BLE001
        logger.debug("node %s: no 0x%04X (%s)", node.id, index, exc)
        return ""


def read_identity(attached: Attached, node_id: int) -> dict[str, str]:
    """What a node says of itself: ``fwVersion``, ``fwImage``, ``build``, ``mac`` (the keys of the
    master's scan, so `newswitch.drivers.uc2.firmware.node_from_scan` reads both)."""
    node = attached.node(node_id)
    return {
        "fwVersion": _string(node, FIRMWARE_VERSION),
        "fwImage": _string(node, BOARD_IMAGE),
        "build": _string(node, BUILD_TIMESTAMP),
        "mac": _string(node, MAC_ADDRESS),
    }


def flash_node(
    attached: Attached,
    node_id: int,
    image: bytes,
    progress: Optional[Callable[[int], None]] = None,
) -> None:
    """Send `image` (an app image) to a node's OTA, which writes it and reboots into it.

    Raises:
        ValueError: The image is larger than a node takes.
        RuntimeError: The node reports the update failed.
    """
    if len(image) > OTA_MAX_SIZE:
        raise ValueError(f"the image is {len(image)} bytes, a node takes at most {OTA_MAX_SIZE}")
    node = attached.node(node_id)
    node.sdo.download(OTA_CRC32, 0, struct.pack("<I", zlib.crc32(image) & 0xFFFFFFFF))
    node.sdo.download(OTA_SIZE, 0, struct.pack("<I", len(image)))  # starts the update
    time.sleep(0.5)  # the node prepares its partition
    with node.sdo.open(OTA_DATA, 0, "wb", size=len(image), block_transfer=False) as stream:
        for start in range(0, len(image), 4096):
            stream.write(image[start : start + 4096])
            if progress is not None:
                progress(min(100, (start + 4096) * 100 // len(image)))
    time.sleep(1.0)
    try:
        status = node.sdo.upload(OTA_STATUS, 0)[0]
    except Exception:  # it already rebooted into the new image  # noqa: BLE001
        return
    if status == OTA_FAILED:
        try:
            code = node.sdo.upload(OTA_ERROR, 0)[0]
        except Exception:  # noqa: BLE001
            code = 0
        raise RuntimeError(f"node {node_id}: OTA failed: {OTA_ERRORS.get(code, f'error {code}')}")
    if status != OTA_COMPLETE:
        logger.warning("node %s: OTA status 0x%02X after the transfer", node_id, status)
