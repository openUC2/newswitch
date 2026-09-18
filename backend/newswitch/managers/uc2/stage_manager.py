"""UC2 stage manager: implements the StageManager protocol over a UC2 bus.

Transport-agnostic — works identically over CANopen (``UC2CanBus``) and
serial (``UC2RestBus``). All positions are micrometers (degrees for axis A);
unit conversion to hardware steps happens inside the bus. Position telemetry
flows back into ``StageState`` via the UC2 event dispatcher (see
``newswitch.managers.uc2.dispatch``), not through this manager.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional

from koil import unkoil
from rekuest_next import model
from rekuest_next.state.lock import acquired_locks

from newswitch.protocols.stage import StageState
from newswitch.protocols.uc2 import UC2BusManager


@model
@dataclass
class UC2StageConfig:
    """Configuration for the UC2 stage manager."""

    axes: list[str] = field(default_factory=lambda: ["X", "Y", "Z", "A"])
    # Homing order matters mechanically: lift Z away from the sample first.
    home_axes: list[str] = field(default_factory=lambda: ["Z", "X", "Y"])
    registered_step_sizes: list[float] = field(
        default_factory=lambda: [10.0, 100.0, 1000.0, 10000.0]
    )
    default_speed: float = 5000.0  # micrometers per second


class UC2StageManager:
    """Stage manager driving openUC2 motors through the UC2 bus."""

    state: StageState

    def __init__(
        self,
        stage_state: StageState,
        bus: UC2BusManager,
        config: Optional[UC2StageConfig] = None,
    ) -> None:
        """Initialize with the shared stage state and a connected UC2 bus."""
        self.bus = bus
        self.stage_state = stage_state
        self.state = stage_state
        self.config = config or UC2StageConfig()
        if not self.config.registered_step_sizes or any(
            step <= 0 for step in self.config.registered_step_sizes
        ):
            raise ValueError("registered_step_sizes must contain positive values")
        with acquired_locks("stage_position"):
            self.stage_state.registered_step_sizes = list(self.config.registered_step_sizes)

    def move(
        self,
        x: Optional[float] = None,
        y: Optional[float] = None,
        z: Optional[float] = None,
        a: Optional[float] = None,
        step_size: Optional[float] = None,
        is_absolute: bool = False,
    ) -> None:
        """Move the stage; blocks until all requested axes finished moving.

        Cancellation (e.g. from the UI) propagates into the bus, which stops
        the affected axes on the hardware.
        """
        unkoil(self._amove, x, y, z, a, is_absolute)

    async def _amove(
        self,
        x: Optional[float],
        y: Optional[float],
        z: Optional[float],
        a: Optional[float],
        is_absolute: bool,
    ) -> None:
        """Move all requested axes concurrently and await completion."""
        targets = {"X": x, "Y": y, "Z": z, "A": a}
        moves = [
            self.bus.amove_axis(
                axis,
                target,
                is_absolute=is_absolute,
                speed=self.config.default_speed,
            )
            for axis, target in targets.items()
            if target is not None and axis in self.config.axes
        ]
        if not moves:
            return
        await asyncio.gather(*moves)

    def move_home(self) -> None:
        """Home the configured axes in mechanically safe order (Z first)."""
        unkoil(self._ahome)

    async def _ahome(self) -> None:
        """Home axes sequentially in the configured order."""
        for axis in self.config.home_axes:
            if axis in self.config.axes:
                await self.bus.ahome_axis(axis)
