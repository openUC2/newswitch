"""Virtual UC2 bus: simulates openUC2 hardware behind the UC2BusManager protocol.

Lets the whole UC2 vertical (device managers, event dispatch, registered
functions, frontend) run and be tested without hardware, emitting the same
typed events a real transport would.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional

from rekuest_next import model

from newswitch.managers.uc2.event_broker import UC2EventBroker
from newswitch.protocols.uc2 import (
    STAGE_AXES,
    MotionDone,
    PositionUpdate,
    HomingChanged,
    UC2Event,
    UC2State,
)


@model
@dataclass
class VirtualUC2BusConfig:
    """Configuration for the simulated UC2 bus."""

    default_speed: float = 5000.0  # micrometers per second
    update_interval_s: float = 0.05  # position telemetry period during moves
    laser_channels: int = 3
    galvo_range: int = 4095  # 12-bit DAC
    objective_slots: int = 2
    fake_nodes: Optional[list[int]] = None  # None -> [11, 12, 13, 20, 21]


class VirtualUC2Bus:
    """Simulated UC2 hardware bus implementing the UC2BusManager protocol."""

    state: UC2State

    def __init__(self, state: UC2State, config: Optional[VirtualUC2BusConfig] = None) -> None:
        """Initialize the simulator with shared bus state."""
        self.state = state
        self.config = config or VirtualUC2BusConfig()
        self._broker = UC2EventBroker()
        self._positions: dict[str, float] = {axis: 0.0 for axis in STAGE_AXES}
        self._lasers: dict[int, int] = {}
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

    async def ahome_axis(self, axis: str) -> None:
        """Simulate homing: drive to zero and emit homing status transitions."""
        self._broker.bind_loop()
        self._broker.publish(HomingChanged(axis=axis, status=1))
        await self.amove_axis(axis, 0.0, is_absolute=True)
        self._broker.publish(HomingChanged(axis=axis, status=2))

    async def aget_position(self, axis: str) -> float:
        """Return the simulated axis position."""
        return self._positions[axis]

    # -- bus / fleet -------------------------------------------------------------

    async def ascan_nodes(self, timeout: float = 3.0) -> list[int]:
        """Return the configured fake node list and mirror it into state."""
        nodes = (
            self.config.fake_nodes if self.config.fake_nodes is not None else [11, 12, 13, 20, 21]
        )
        self.state.nodes_online = sorted(nodes)
        return sorted(nodes)

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

    async def aset_laser(self, channel: int, value: int) -> None:
        """Store the simulated laser PWM value."""
        self._lasers[channel] = value

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
