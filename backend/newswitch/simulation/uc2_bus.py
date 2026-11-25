"""Virtual UC2 bus: simulates openUC2 hardware behind the UC2BusManager protocol.

Lets the whole UC2 vertical (device managers, event dispatch, registered
functions, frontend) run and be tested without hardware, emitting the same
typed events a real transport would.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, AsyncIterator, Optional

from newswitch.drivers.uc2.event_broker import UC2EventBroker
from newswitch.drivers.uc2.firmware import wanting
from newswitch.instrument.hardware import Firmware
from newswitch.models.uc2 import (
    STAGE_AXES,
    HomingChanged,
    MotionDone,
    PositionUpdate,
    UC2Event,
    UC2Node,
)
from newswitch.states.uc2 import UC2State

if TYPE_CHECKING:  # pragma: no cover
    from newswitch.drivers.uc2.firmware import FirmwareImage, Report

#: What a simulated node is, by its node id (as the uc2canopen node map has them).
_VIRTUAL_KINDS = {
    11: "motor",
    12: "motor",
    13: "motor",
    14: "motor",
    20: "led",
    21: "laser",
    30: "galvo",
}


#: Which node of a board's node map is what kind of satellite.
_NODE_FIELDS = {
    "node_a": "motor",
    "node_x": "motor",
    "node_y": "motor",
    "node_z": "motor",
    "node_laser": "laser",
    "node_led": "led",
    "node_galvo": "galvo",
}


@dataclass
class VirtualUC2BusConfig:
    """Configuration for the simulated UC2 bus."""

    default_speed: float = 5000.0  # micrometers per second
    update_interval_s: float = 0.05  # position telemetry period during moves
    laser_channels: int = 3
    galvo_range: int = 4095  # 12-bit DAC
    objective_slots: int = 2
    fake_nodes: Optional[list[int]] = None  # None -> [11, 12, 13, 20, 21]
    node_kinds: Optional[dict[int, str]] = None
    """What each node is (a board's node map); None: uc2canopen's defaults."""
    homing: dict[str, dict[str, int]] = field(default_factory=dict)
    """How each axis homes, as a real board's ``homing``: here only its ``release`` (steps backed
    off from the endstop) matters."""
    steps_per_um: dict[str, float] = field(default_factory=dict)
    """Steps per micrometre by axis, to turn a release in steps into where the axis ends."""
    allow_motion: bool = True
    port_board: bool = True
    """Whether the board is on a port (the serial master); a CAN bus has none."""

    @classmethod
    def from_board(cls, options: Mapping[str, Any], transport: str) -> "VirtualUC2BusConfig":
        """The virtual twin of a board, from the options it is built with (`bus_options`): its node
        map, how its axes home and how many steps they take, whether it may move. What only the
        link needs (channel, bitrate, port) means nothing here."""
        kinds = {
            int(options[name]): kind for name, kind in _NODE_FIELDS.items() if name in options
        }
        steps = {
            axis: float(options[key])
            for axis, key in (
                ("X", "steps_per_um_x"),
                ("Y", "steps_per_um_y"),
                ("Z", "steps_per_um_z"),
                ("A", "steps_per_deg_a"),
            )
            if key in options
        }
        homing = {str(axis).upper(): dict(how) for axis, how in options.get("homing", {}).items()}
        return cls(
            fake_nodes=sorted(kinds) if kinds else None,
            node_kinds=kinds or None,
            homing=homing,
            steps_per_um=steps,
            allow_motion=bool(options.get("allow_motion", True)),
            port_board=transport != "canopen",
        )


class VirtualUC2Bus:
    """Simulated UC2 hardware bus implementing the UC2BusManager protocol."""

    state: UC2State
    keeps_firmware = False
    has_port_board = True

    def __init__(
        self,
        state: UC2State,
        config: Optional[VirtualUC2BusConfig] = None,
        firmware: Optional[Firmware] = None,
    ) -> None:
        """Initialize the simulator with shared bus state, and what its description says it runs."""
        self.state = state
        self.config = config or VirtualUC2BusConfig()
        self.firmware = firmware
        self.has_port_board = self.config.port_board
        kinds = self.config.node_kinds or _VIRTUAL_KINDS
        self._board = UC2Node(
            can_id=1,
            kind="master",
            status="connected",
            firmware="virtual",
            image="esp32_UC2_canopen_master_release.bin",
            build="virtual",
        )
        ids = self.config.fake_nodes if self.config.fake_nodes is not None else [11, 12, 13, 20, 21]
        self._nodes = {
            can_id: UC2Node(
                can_id=can_id,
                kind=kinds.get(can_id, "motor"),
                status="idle",
                firmware="virtual",
                image=f"esp32_UC2_canopen_slave_{kinds.get(can_id, 'motor')}_release.bin",
                build="virtual",
                mac=f"02:00:00:00:00:{can_id:02X}",
            )
            for can_id in ids
        }
        self.flashed: list[Optional[int]] = []
        """What was flashed, in order: None for the board, else the node id."""
        self._broker = UC2EventBroker()
        self._positions: dict[str, float] = {axis: 0.0 for axis in STAGE_AXES}
        self._lasers: dict[Any, int] = {}
        self._galvo_xy: tuple[int, int] = (0, 0)
        self._galvo_scanning = False
        self._objective_slot = 1
        self._stop_flags: dict[str, asyncio.Event] = {axis: asyncio.Event() for axis in STAGE_AXES}

    # -- lifecycle -------------------------------------------------------------

    async def abackground(self) -> None:
        """Mark the virtual bus connected and idle forever."""
        self._broker.bind_loop()
        self.state.connected = True
        self.state.transport = "virtual"
        self.state.firmware = "virtual-uc2"
        await asyncio.Event().wait()

    # -- stage -------------------------------------------------------------------

    async def amove_axis(
        self,
        axis: str,
        target: float,
        is_absolute: bool = False,
        speed: Optional[float] = None,
        acceleration: Optional[float] = None,
    ) -> float:
        """Simulate a constant-velocity move, emitting telemetry and MotionDone."""
        self._may_move("amove_axis")
        self._broker.bind_loop()
        speed = speed or self.config.default_speed
        start = self._positions[axis]
        goal = target if is_absolute else start + target
        distance = goal - start
        duration = abs(distance) / max(speed, 1e-9)
        steps = max(1, int(duration / self.config.update_interval_s))
        self._stop_flags[axis].clear()

        try:
            for i in range(1, steps + 1):
                if self._stop_flags[axis].is_set():
                    break
                await asyncio.sleep(duration / steps)
                self._positions[axis] = start + distance * i / steps
                self._broker.publish(PositionUpdate(axis=axis, position=self._positions[axis]))
        except asyncio.CancelledError:
            self._broker.publish(MotionDone(axis=axis, position=self._positions[axis]))
            raise
        self._broker.publish(MotionDone(axis=axis, position=self._positions[axis]))
        return self._positions[axis]

    async def astop_axis(self, axis: str) -> None:
        """Interrupt a running simulated move."""
        self._stop_flags[axis].set()

    def _may_move(self, what: str) -> None:
        """Refuse motion as a real board with ``allow_motion: false`` does.

        Raises:
            PermissionError: Its motion is disabled.
        """
        if not self.config.allow_motion:
            raise PermissionError(
                f"{what}: motion is disabled on this board (allow_motion: false); nothing was sent"
            )

    def released(self, axis: str) -> float:
        """Where homing leaves `axis`: the endstop (0), less the back-off its homing states, in
        micrometres (degrees for A)."""
        release = self.config.homing.get(axis.upper(), {}).get("release", 0)
        steps_per_unit = self.config.steps_per_um.get(axis.upper())
        return release / steps_per_unit if release and steps_per_unit else 0.0

    async def ahome_axis(self, axis: str) -> None:
        """Simulate homing: drive to the endstop (0), back off as its homing says, and emit the
        homing status transitions."""
        self._may_move("ahome_axis")
        self._broker.bind_loop()
        self._broker.publish(HomingChanged(axis=axis, status=1))
        await self.amove_axis(axis, 0.0, is_absolute=True)
        if self.released(axis):
            await self.amove_axis(axis, self.released(axis), is_absolute=True)
        self._broker.publish(HomingChanged(axis=axis, status=2))

    async def aget_position(self, axis: str) -> float:
        """Return the simulated axis position."""
        return self._positions[axis]

    # -- bus / fleet -------------------------------------------------------------

    async def ascan_nodes(self, timeout: float = 3.0) -> list[UC2Node]:
        """The simulated nodes, mirrored into state."""
        self.state.nodes_online = sorted(self._nodes)
        return [wanting(self._nodes[can_id], self.firmware) for can_id in sorted(self._nodes)]

    async def aidentify(self) -> Optional[UC2Node]:
        """The simulated master on the port; none on a CAN bus, which has no board on a port."""
        if not self.has_port_board:
            return None
        return wanting(self._board, self.firmware, board=True)

    # -- firmware ------------------------------------------------------------------

    def _flashed(self, node: UC2Node, image: "FirmwareImage") -> UC2Node:
        name = image.path.name.replace("_merged.bin", ".bin")
        return replace(node, image=name, firmware=image.version or "virtual")

    async def aflash_board(self, image: "FirmwareImage", report: "Report") -> None:
        """Pretend to write the board: it then runs the image."""
        for percent in (0, 50, 100):
            report(f"writing {image.path.name}", percent)
            await asyncio.sleep(0)
        self._board = self._flashed(self._board, image)
        self.flashed.append(None)

    async def aflash_node(self, can_id: int, image: "FirmwareImage", report: "Report") -> None:
        """Pretend to send a node its image: it then runs it."""
        if can_id not in self._nodes:
            raise RuntimeError(f"node {can_id} is not on the bus")
        report(f"sending {image.path.name}", 100)
        self._nodes[can_id] = self._flashed(self._nodes[can_id], image)
        self.flashed.append(can_id)

    # -- objective changer -------------------------------------------------------

    async def aobjective_move(self, slot: int) -> None:
        """Store the simulated objective slot after a short travel delay."""
        await asyncio.sleep(self.config.update_interval_s)
        self._objective_slot = slot

    async def aobjective_home(self) -> None:
        """Home the simulated objective changer to slot 1."""
        await asyncio.sleep(self.config.update_interval_s)
        self._objective_slot = 1

    async def aobjective_status(self) -> dict[str, Any]:
        """Return the simulated objective status."""
        return {"slot": self._objective_slot, "homed": True}

    # -- illumination ---------------------------------------------------------------

    async def aset_laser(self, channel: int, value: int, node: Optional[int] = None) -> None:
        """Store the simulated laser PWM value, of its node's channel."""
        self._lasers[(node, channel)] = value

    async def aled_fill(self, r: int, g: int, b: int) -> None:
        """Simulate filling the LED matrix (no-op beyond bookkeeping)."""
        self._lasers[-1] = (r << 16) | (g << 8) | b

    async def aled_off(self) -> None:
        """Simulate turning the LED matrix off."""
        self._lasers[-1] = 0

    # -- galvo -------------------------------------------------------------------------

    async def agalvo_goto(self, x: int, y: int) -> None:
        """Store the simulated galvo position."""
        self._galvo_xy = (x, y)

    async def agalvo_raster(
        self,
        x_min: int,
        x_max: int,
        y_min: int,
        y_max: int,
        nx: int,
        ny: int,
        pixel_dwell_us: int = 1,
        trigger_mode: int = 1,
        bidirectional: bool = False,
    ) -> None:
        """Mark a simulated raster scan as active."""
        self._galvo_scanning = True

    async def agalvo_stop(self) -> None:
        """Stop the simulated galvo scan."""
        self._galvo_scanning = False

    async def agalvo_status(self) -> dict[str, Any]:
        """Return simulated galvo status flags."""
        return {
            "raw": 2 if self._galvo_scanning else 0,
            "moving": False,
            "scan_active": self._galvo_scanning,
            "scan_complete": not self._galvo_scanning,
            "error": False,
        }

    # -- events ---------------------------------------------------------------------------

    def subscribe(self) -> AsyncIterator[UC2Event]:
        """Yield simulated hardware events."""
        return self._broker.subscribe()
