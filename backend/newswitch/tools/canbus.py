"""What a UC2 CAN bus carries: every frame the Pi sends and the nodes answer, decoded, as it happens.

    just canbus                          # what changes: commands, answers, moves, state changes
    just canbus --all                    # every frame, the periodic ones that repeat too
    just canbus --node Z --node laser    # only these nodes (a name from the node map, or an id)
    just canbus --channel can0 --config instruments/johannes-frame

It only listens: it opens a socket of its own on the SocketCAN interface and sends nothing, so it
runs beside the agent (the kernel hands every socket on the host the frames the others send). A
Waveshare USB-CAN adapter is a serial port only one process can hold: it cannot be watched so.

Which node is which comes from the description (``--config``, else ``NEWSWITCH_CONFIG``: its board's
``node_x``, ``node_laser``, ...), the objects' names and types from the firmware's object
dictionary (`uc2canopen.od`). The direction is CANopen's: the Pi is the SDO client and the NMT and
SYNC master, so a request (0x600 + node), an RPDO, NMT and SYNC go out (``->``); an answer
(0x580 + node), a TPDO, an emergency and a heartbeat come in (``<-``).

Without ``--all``, a periodic frame (a TPDO, a heartbeat, SYNC) is shown when its node sent nothing
the same in the last `REPEATS_S` seconds: a motor reporting where it stands every half second is
shown once (also when it alternates, as a node at rest reports 0 now and then), every position of
a move is. The segments of an SDO transfer are shown as the one value they make.
Ctrl-C stops it and says how much went each way.
"""

from __future__ import annotations

import argparse
import os
import struct
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

#: How long a periodic frame that came before is left out when it comes again, in seconds.
REPEATS_S = 3.0

#: What CANopen's function code (the COB-ID's top four bits) says a frame is.
NMT, SYNC_EMCY, TPDO1, RPDO1, TPDO2, RPDO2, TPDO3, RPDO3, TPDO4, RPDO4 = (
    0x000,
    0x080,
    0x180,
    0x200,
    0x280,
    0x300,
    0x380,
    0x400,
    0x480,
    0x500,
)
SDO_RESPONSE, SDO_REQUEST, HEARTBEAT = 0x580, 0x600, 0x700

#: What goes out from the Pi (the client, the master); everything else comes in.
_SENT = {NMT, RPDO1, RPDO2, RPDO3, RPDO4, SDO_REQUEST}

NMT_COMMANDS = {
    0x01: "start",
    0x02: "stop",
    0x80: "enter pre-operational",
    0x81: "reset node",
    0x82: "reset communication",
}
NMT_STATES = {0x00: "boot-up", 0x04: "stopped", 0x05: "operational", 0x7F: "pre-operational"}
HOMING = {0: "idle", 1: "homing", 2: "done", 3: "timeout"}

SDO_ABORTS = {
    0x05030000: "toggle bit not alternated",
    0x05040000: "SDO protocol timed out",
    0x05040001: "unknown command",
    0x05040005: "out of memory",
    0x06010000: "unsupported access",
    0x06010001: "write-only object",
    0x06010002: "read-only object",
    0x06020000: "no such object",
    0x06040041: "cannot be mapped to a PDO",
    0x06060000: "hardware error",
    0x06070010: "wrong length",
    0x06070012: "too long",
    0x06070013: "too short",
    0x06090011: "no such subindex",
    0x06090030: "value out of range",
    0x06090031: "value too high",
    0x06090032: "value too low",
    0x08000000: "general error",
    0x08000020: "cannot be stored or used now",
    0x08000021: "cannot, under local control",
    0x08000022: "cannot, in this device state",
}

#: CANopen's own objects (below the manufacturer area the firmware's are in).
STANDARD_OBJECTS = {
    0x1000: "device_type",
    0x1001: "error_register",
    0x1003: "error_history",
    0x1008: "device_name",
    0x1009: "hardware_version",
    0x100A: "software_version",
    0x1017: "heartbeat_time",
    0x1018: "identity",
    0x1F50: "program_data",
    0x1F51: "program_control",
    0x1F56: "program_software_id",
    0x1F57: "flash_status",
}

#: Which node is which when no description says: uc2canopen's defaults (`UC2CanBusConfig`).
DEFAULT_NODE_MAP = {
    "node_a": 14,
    "node_x": 11,
    "node_y": 12,
    "node_z": 13,
    "node_laser": 21,
    "node_led": 20,
    "node_galvo": 30,
}
_NODE_LABELS = {
    "node_a": "A",
    "node_x": "X",
    "node_y": "Y",
    "node_z": "Z",
    "node_laser": "laser",
    "node_led": "led",
    "node_galvo": "galvo",
}


@dataclass(frozen=True)
class ObjectType:
    """What an object of the dictionary is called, and how its value is packed (None: bytes)."""

    name: str
    fmt: str | None = None


def object_types() -> dict[int, ObjectType]:
    """The firmware's objects, by index: named and typed by `uc2canopen.od`, CANopen's named."""
    from uc2canopen.od import OD, SDO_TYPES

    types = {index: ObjectType(name) for index, name in STANDARD_OBJECTS.items()}
    for attribute, index in vars(OD).items():
        if attribute.isupper() and isinstance(index, int):
            types.setdefault(index, ObjectType(attribute.lower()))  # the first name, not an alias
    for index, entry in SDO_TYPES.items():
        types[index] = ObjectType(entry.name, entry.fmt)
    return types


def node_names(options: dict[str, object]) -> dict[int, str]:
    """Each node's name from a board's options (``node_x: 11``, ...); several on one id share it."""
    names: dict[int, list[str]] = {1: ["master"]}
    for key, label in _NODE_LABELS.items():
        node = options.get(key, DEFAULT_NODE_MAP[key])
        if isinstance(node, int) and 0 < node < 128:
            names.setdefault(node, []).append(label)
    return {node: "/".join(labels) for node, labels in names.items()}


@dataclass
class Frame:
    """One frame, decoded."""

    sent: bool
    """Whether the Pi sent it (a request, an RPDO, NMT, SYNC), or a node did."""
    node: int
    """The node it is from or for; 0 for what goes to every node (NMT to all, SYNC)."""
    kind: str
    text: str
    periodic: bool = False
    """Whether it comes again and again (a TPDO, a heartbeat, SYNC): shown when it changes."""
    alarm: bool = False
    """Whether something went wrong (an SDO abort, an emergency)."""
    part: bool = False
    """Whether it is one segment of a transfer, shown whole when it ends."""


@dataclass
class _Transfer:
    """An SDO transfer of several segments, while it goes."""

    upload: bool
    index: int
    sub: int
    size: int | None
    data: bytearray = field(default_factory=bytearray)
    segments: int = 0
    block: bool = False


class Decoder:
    """Decodes frames, keeping what spans several: the SDO transfers of each node."""

    def __init__(
        self, types: dict[int, ObjectType] | None = None, motors: set[int] | None = None
    ) -> None:
        """`types`: the dictionary (default: `object_types`); `motors`: see `motors`."""
        self.types = object_types() if types is None else types
        self.motors = motors
        """The motor nodes, whose TPDO1 is a position (None: every node's is)."""
        self._transfers: dict[int, _Transfer] = {}

    def decode(self, cob_id: int, data: bytes) -> Frame:
        """What the frame `data` on `cob_id` says."""
        function, node = cob_id & 0x780, cob_id & 0x07F
        sent = function in _SENT or cob_id == SYNC_EMCY
        if cob_id == NMT:
            return self._nmt(data)
        if cob_id == SYNC_EMCY:
            return Frame(True, 0, "SYNC", "sync" + (f" {data[0]}" if data else ""), periodic=True)
        if function == SYNC_EMCY:
            return _emergency(node, data)
        if function == HEARTBEAT:
            state = data[0] & 0x7F if data else -1
            text = NMT_STATES.get(state, f"state 0x{state:02X}")
            return Frame(False, node, "HB", text, periodic=state != 0x00)
        if function in (SDO_REQUEST, SDO_RESPONSE):
            return self._sdo(function == SDO_REQUEST, node, data)
        motor = self.motors is None or node in self.motors
        if function == TPDO1 and len(data) >= 5 and motor:
            position, status = struct.unpack_from("<iB", data)
            text = f"at {position} steps, {'running' if status & 0x01 else 'stopped'}"
            if status & ~0x01:
                text += f" (status 0x{status:02X})"
            if len(data) >= 6:
                text += f", homing {HOMING.get(data[5], data[5])}"
            return Frame(False, node, "TPDO1", text, periodic=True)
        if function == TPDO3 and len(data) >= 6 and motor:
            position, count = struct.unpack_from("<iH", data)
            text = f"latched {position} steps at SYNC #{count}"
            return Frame(False, node, "TPDO3", text, periodic=True)
        names = {
            TPDO1: "TPDO1", TPDO2: "TPDO2", TPDO3: "TPDO3", TPDO4: "TPDO4",
            RPDO1: "RPDO1", RPDO2: "RPDO2", RPDO3: "RPDO3", RPDO4: "RPDO4",
        }  # fmt: skip
        kind = names.get(function, f"0x{function:03X}")
        return Frame(sent, node, kind, data.hex(" ") or "(empty)", periodic=kind.startswith("T"))

    def _nmt(self, data: bytes) -> Frame:
        command, target = (data[0], data[1]) if len(data) >= 2 else (-1, 0)
        text = NMT_COMMANDS.get(command, f"command 0x{command:02X}")
        return Frame(True, target, "NMT", text + ("" if target else " (every node)"))

    def _object(self, index: int, sub: int) -> str:
        known = self.types.get(index)
        name = known.name if known is not None else f"0x{index:04X}"
        return f"{name}[{sub}]" if sub else name

    def _value(self, index: int, raw: bytes) -> str:
        """`raw` as the object's type packs it: a number if it is one, else text or bytes."""
        known = self.types.get(index)
        if (
            known is not None
            and known.fmt is not None
            and struct.calcsize("<" + known.fmt) == len(raw)
        ):
            value = struct.unpack("<" + known.fmt, raw)[0]
            if index == 0x2016:
                return f"{value} ({HOMING.get(value, '?')})"
            return str(value)
        if raw and all(32 <= b < 127 for b in raw.rstrip(b"\0")) and raw.rstrip(b"\0"):
            return repr(raw.rstrip(b"\0").decode())
        if len(raw) <= 4:
            return f"{int.from_bytes(raw, 'little')} (0x{raw[::-1].hex() or '0'})"
        return raw.hex(" ")

    def _sdo(self, request: bool, node: int, data: bytes) -> Frame:
        kind = "SDO"
        if len(data) < 8:
            return Frame(request, node, kind, f"short frame {data.hex(' ')}", alarm=True)
        transfer = self._transfers.get(node)
        if transfer is not None and transfer.block:
            return self._block(request, node, data, transfer)
        command = data[0] >> 5
        index, sub = struct.unpack_from("<HB", data, 1)
        where = self._object(index, sub)
        if command == 4:  # abort, either way
            self._transfers.pop(node, None)
            code = struct.unpack_from("<I", data, 4)[0]
            reason = SDO_ABORTS.get(code, "unknown reason")
            return Frame(request, node, kind, f"ABORT {where}: {reason} (0x{code:08X})", alarm=True)
        if request:
            return self._request(node, data, command, index, sub, where)
        return self._response(node, data, command, index, sub, where)

    def _request(
        self, node: int, data: bytes, command: int, index: int, sub: int, where: str
    ) -> Frame:
        if command == 1:  # initiate download: a write
            if data[0] & 0x02:  # expedited: the value is in this frame
                size = 4 - ((data[0] >> 2) & 0x03) if data[0] & 0x01 else 4
                value = self._value(index, data[4 : 4 + size])
                return Frame(True, node, "SDO", f"write {where} = {value}")
            size = struct.unpack_from("<I", data, 4)[0] if data[0] & 0x01 else None
            self._transfers[node] = _Transfer(False, index, sub, size)
            return Frame(True, node, "SDO", f"write {where}, {size or '?'} bytes in segments")
        if command == 2:  # initiate upload: a read
            return Frame(True, node, "SDO", f"read {where}")
        if command == 0:  # a download segment
            transfer = self._transfers.get(node)
            if transfer is None:
                return Frame(True, node, "SDO", "segment of no transfer", alarm=True)
            unused = (data[0] >> 1) & 0x07
            transfer.data += data[1 : 8 - unused]
            transfer.segments += 1
            if data[0] & 0x01:  # the last
                del self._transfers[node]
                what = self._object(transfer.index, transfer.sub)
                text = f"wrote {what}: {len(transfer.data)} bytes in {transfer.segments} segments"
                if len(transfer.data) <= 64:
                    text += f" = {self._value(transfer.index, bytes(transfer.data))}"
                return Frame(True, node, "SDO", text)
            return Frame(True, node, "SDO", f"segment {transfer.segments}", part=True)
        if command == 3:  # an upload segment asked for
            return Frame(True, node, "SDO", "next segment", part=True)
        if command in (5, 6):  # block upload / download
            upload = command == 5
            self._transfers[node] = _Transfer(upload, index, sub, None, block=True)
            way = "read" if upload else "write"
            return Frame(True, node, "SDO", f"block {way} {where}")
        return Frame(True, node, "SDO", f"command {command} {data.hex(' ')}", alarm=True)

    def _response(
        self, node: int, data: bytes, command: int, index: int, sub: int, where: str
    ) -> Frame:
        if command == 3:  # download initiated / done: the write is taken
            return Frame(False, node, "SDO", f"ok, {where} written")
        if command == 2:  # upload initiated: the value, or its size
            if data[0] & 0x02:
                size = 4 - ((data[0] >> 2) & 0x03) if data[0] & 0x01 else 4
                return Frame(
                    False, node, "SDO", f"{where} = {self._value(index, data[4 : 4 + size])}"
                )
            size = struct.unpack_from("<I", data, 4)[0] if data[0] & 0x01 else None
            self._transfers[node] = _Transfer(True, index, sub, size)
            return Frame(
                False, node, "SDO", f"{where}: {size or '?'} bytes, in segments", part=True
            )
        if command == 0:  # an upload segment
            transfer = self._transfers.get(node)
            if transfer is None:
                return Frame(False, node, "SDO", "segment of no transfer", alarm=True)
            unused = (data[0] >> 1) & 0x07
            transfer.data += data[1 : 8 - unused]
            transfer.segments += 1
            if data[0] & 0x01:
                del self._transfers[node]
                what = self._object(transfer.index, transfer.sub)
                return Frame(
                    False,
                    node,
                    "SDO",
                    f"{what} = {self._value(transfer.index, bytes(transfer.data))}",
                )
            return Frame(False, node, "SDO", f"segment {transfer.segments}", part=True)
        if command == 1:  # a download segment taken
            return Frame(False, node, "SDO", "segment taken", part=True)
        return Frame(False, node, "SDO", f"command {command} {data.hex(' ')}", alarm=True)

    def _block(self, request: bool, node: int, data: bytes, transfer: _Transfer) -> Frame:
        """A frame of a block transfer: its data, its acknowledgements, until it ends."""
        transfer.segments += 1
        if not request and data[0] >> 5 == 5 and data[0] & 0x03 == 1 and not transfer.upload:
            del self._transfers[node]  # the server's "block download ended"
            what = self._object(transfer.index, transfer.sub)
            return Frame(
                False, node, "SDO", f"block write of {what} done, {transfer.segments} frames"
            )
        if request and data[0] >> 5 == 5 and data[0] & 0x03 == 1 and transfer.upload:
            del self._transfers[node]  # the client's "block upload ended"
            what = self._object(transfer.index, transfer.sub)
            return Frame(
                True, node, "SDO", f"block read of {what} done, {transfer.segments} frames"
            )
        return Frame(request, node, "SDO", f"block frame {data.hex(' ')}", part=True)


def _emergency(node: int, data: bytes) -> Frame:
    if len(data) < 3:
        return Frame(False, node, "EMCY", data.hex(" "), alarm=True)
    code, register = struct.unpack_from("<HB", data)
    if code == 0:
        return Frame(False, node, "EMCY", "error reset (no error)")
    text = f"error 0x{code:04X}, register 0x{register:02X}"
    if len(data) > 3:
        text += f", vendor {data[3:].hex(' ')}"
    return Frame(False, node, "EMCY", text, alarm=True)


# --------------------------------------------------------------------------- the live view


def _say(line: str = "", error: bool = False) -> None:
    """A line of the live view, written at once: it is a stream, not a log."""
    stream = sys.stderr if error else sys.stdout
    stream.write(line + "\n")
    stream.flush()


class _Style:
    """Terminal colours, or none when the output is not a terminal."""

    def __init__(self, enabled: bool) -> None:
        def code(n: str) -> str:
            return f"\033[{n}m" if enabled else ""

        self.sent, self.received, self.alarm = code("36"), code("32"), code("1;31")
        self.dim, self.reset = code("2"), code("0")


def _bus_state(channel: str) -> str:
    """What the kernel says of the interface: its state and bitrate, as ``ip`` reports them."""
    try:
        shown = subprocess.run(
            ["ip", "-details", "link", "show", channel],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return "state unknown"
    words = shown.split()
    found = []
    for key in ("state", "bitrate"):
        positions = [i for i, w in enumerate(words) if w == key]
        if positions:
            found.append(f"{key} {words[positions[-1] + 1]}")  # the CAN state, after the link's
    return ", ".join(found) or "state unknown"


def _description(path: str | None) -> tuple[dict[str, object], str | None]:
    """The board options of the description at `path` (else ``NEWSWITCH_CONFIG``), and its name."""
    from newswitch.settings import CONFIG_ENV_VAR

    path = path or os.environ.get(CONFIG_ENV_VAR)
    if not path:
        return {}, None
    from newswitch.instrument import spec

    instrument = spec.load(path)
    if instrument.hardware.board is None:
        return {}, instrument.name
    return dict(instrument.hardware.board.options), instrument.name


def _wanted(nodes: list[str], names: dict[int, str]) -> set[int] | None:
    """The node ids `nodes` names (ids, or names from the node map); None: every node."""
    if not nodes:
        return None
    by_name = {part.lower(): node for node, name in names.items() for part in name.split("/")}
    wanted = set()
    for given in nodes:
        if given.isdigit():
            wanted.add(int(given))
        elif given.lower() in by_name:
            wanted.add(by_name[given.lower()])
        else:
            raise SystemExit(f"no node {given!r}: the node map has {', '.join(sorted(by_name))}")
    return wanted


def watch(args: argparse.Namespace) -> int:
    """Print what the bus carries until Ctrl-C, then how much went each way."""
    import can

    options, instrument = _description(args.config)
    names = node_names(options)
    channel = args.channel or str(options.get("channel") or "can0")
    wanted = _wanted(args.node, names)
    style = _Style(sys.stdout.isatty() and not args.no_color)
    motors = {node for node, name in names.items() if set(name.split("/")) & {"A", "X", "Y", "Z"}}
    decoder = Decoder(motors=motors)
    seen: dict[tuple[int, bytes], float] = {}
    counts: Counter[tuple[str, int]] = Counter()
    hidden = 0

    mapped = ", ".join(f"{name} {node}" for node, name in sorted(names.items()))
    source = f"the description of {instrument}" if instrument else "uc2canopen's defaults"
    _say(f"Listening on {channel} ({_bus_state(channel)}); nodes from {source}: {mapped}")
    _say("-> the Pi sends, <- a node sends. Ctrl-C stops." + ("" if args.all else
          " Repeats of periodic frames are left out (--all shows them)."))  # fmt: skip

    try:
        bus = can.Bus(interface="socketcan", channel=channel, receive_own_messages=False)
    except (OSError, can.CanError) as error:
        _say(f"Cannot open {channel}: {error}", error=True)
        return 1
    try:
        while True:
            message = bus.recv(timeout=1.0)
            if message is None or message.is_error_frame or message.is_remote_frame:
                continue
            cob_id, data = message.arbitration_id, bytes(message.data)
            frame = decoder.decode(cob_id, data)
            counts[("sent" if frame.sent else "received", frame.node)] += 1
            if wanted is not None and (frame.node not in wanted if frame.node else cob_id != NMT):
                continue
            if not args.all:
                key, at = (cob_id, data), message.timestamp
                repeat = frame.periodic and at - seen.get(key, -REPEATS_S) < REPEATS_S
                if frame.periodic:
                    seen[key] = at
                if frame.part or repeat:
                    hidden += 1
                    continue
            stamp = datetime.fromtimestamp(message.timestamp).strftime("%H:%M:%S.%f")[:-3]
            arrow = (
                f"{style.sent}->{style.reset}" if frame.sent else f"{style.received}<-{style.reset}"
            )
            who = f"{names.get(frame.node, '?')} {frame.node}" if frame.node else "all"
            text = f"{style.alarm}{frame.text}{style.reset}" if frame.alarm else frame.text
            raw = f"{style.dim}{cob_id:03X}  {data.hex(' ')}{style.reset}"
            _say(f"{stamp}  {arrow} {who:<10} {frame.kind:<5} {text}   {raw}")
    except KeyboardInterrupt:
        pass
    finally:
        bus.shutdown()

    _say()
    for way in ("sent", "received"):
        per_node = sorted((node, n) for (w, node), n in counts.items() if w == way)
        total = sum(n for _, n in per_node)
        listed = ", ".join(
            f"{names.get(node, node) if node else 'all'}: {n}" for node, n in per_node
        )
        _say(f"{way}: {total} frames" + (f" ({listed})" if listed else ""))
    if hidden:
        _say(f"left out: {hidden} repeats and transfer segments")
    return 0


def main(argv: list[str] | None = None) -> None:
    """``python -m newswitch.tools.canbus``: watch the bus (see the module)."""
    parser = argparse.ArgumentParser(
        prog="canbus", description="What a UC2 CAN bus carries, decoded. It only listens."
    )
    parser.add_argument("--channel", help="the SocketCAN interface (default: the board's, or can0)")
    parser.add_argument(
        "--config",
        help="the description whose node map names the nodes (default: NEWSWITCH_CONFIG)",
    )
    parser.add_argument(
        "--node", action="append", default=[], help="only this node, by id or name (repeatable)"
    )
    parser.add_argument(
        "--all", action="store_true", help="every frame, also periodic ones that did not change"
    )
    parser.add_argument("--no-color", action="store_true", help="no terminal colours")
    sys.exit(watch(parser.parse_args(argv)))


if __name__ == "__main__":
    main()
