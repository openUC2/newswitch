"""
UC2 Hardware Bus Protocol

Transport-agnostic command surface for openUC2 hardware. Two real transports
exist (JSON-over-serial via ``uc2rest`` and CANopen via ``uc2canopen``) plus a
virtual simulator; they are plug-in replacements for each other behind this
protocol. Device managers (stage, illumination, galvo, ...) speak only to
``UC2BusManager`` and never to a concrete transport.

Units convention:
* stage axes are addressed by name ("X", "Y", "Z", "A") in micrometers
  (degrees for "A"); the bus converts to hardware steps internally,
* galvo positions are DAC counts (hardware-native),
* laser values are raw PWM counts.

Spontaneous hardware events (position telemetry, motion-done, homing,
emergency stop, buttons) are exposed as a typed async event stream via
``subscribe()``; a background dispatcher mirrors them into shared states.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional, Protocol, Union, runtime_checkable

from rekuest_next import state
from rekuest_next.agents.context import context

from newswitch.protocols.base import BackgroundManager

STAGE_AXES = ("X", "Y", "Z", "A")


# ---------------------------------------------------------------------------
# Typed hardware events
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PositionUpdate:
    """Live position telemetry for one stage axis (micrometers)."""

    axis: str
    position: float


@dataclass(frozen=True)
class MotionDone:
    """A stage axis finished its motion at ``position`` (micrometers)."""

    axis: str
    position: float


@dataclass(frozen=True)
class HomingChanged:
    """Homing phase change for an axis (0=idle, 1=homing, 2=done, 3=timeout)."""

    axis: str
    status: int


@dataclass(frozen=True)
class EStopChanged:
    """The hardware emergency-stop state changed."""

    active: bool


@dataclass(frozen=True)
class ButtonPressed:
    """A hardware button / firmware key-value event was received."""

    key: Optional[str]
    data: Any


@dataclass(frozen=True)
class NodeSeen:
    """A bus node announced itself (CAN heartbeat or firmware identity)."""

    node_id: int
    nmt_state: int


@dataclass(frozen=True)
class BusError:
    """A transport-level error occurred (link loss, protocol error)."""

    message: str


UC2Event = Union[
    PositionUpdate,
    MotionDone,
    HomingChanged,
    EStopChanged,
    ButtonPressed,
    NodeSeen,
    BusError,
]


# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------


@state
@dataclass
class UC2State:
    """Connection, identity, and safety state of the UC2 hardware bus."""

    connected: bool = False
    transport: str = "virtual"
    firmware: str = ""
    estop_active: bool = False
    nodes_online: list[int] = field(default_factory=list)
    last_error: str = ""


# ---------------------------------------------------------------------------
# Bus protocol
# ---------------------------------------------------------------------------


@context
@runtime_checkable
class UC2BusManager(BackgroundManager, Protocol):
    """Protocol for transport backends driving openUC2 hardware.

    Implementations: ``UC2CanBus`` (CANopen, preferred), ``UC2RestBus``
    (JSON-over-serial via uc2rest), ``VirtualUC2Bus`` (simulation).
    ``abackground()`` (from BackgroundManager) owns connect + event pumping.
    """

    state: UC2State

    # -- stage motion (micrometers; degrees for axis "A") ---------------------

    async def amove_axis(
        self,
        axis: str,
        target: float,
        is_absolute: bool = False,
        speed: Optional[float] = None,
        acceleration: Optional[float] = None,
    ) -> float:
        """Move one axis and wait until motion completes; returns the final position."""
        ...

    async def astop_axis(self, axis: str) -> None:
        """Immediately stop one axis."""
        ...

    async def ahome_axis(self, axis: str) -> None:
        """Home one axis and wait until homing completes."""
        ...

    async def aget_position(self, axis: str) -> float:
        """Read the current position of one axis."""
        ...

    # -- bus / fleet -----------------------------------------------------------

    async def ascan_nodes(self, timeout: float = 3.0) -> list[int]:
        """Discover reachable bus nodes (CAN node ids / firmware CAN scan)."""
        ...

    # -- objective changer -----------------------------------------------------

    async def aobjective_move(self, slot: int) -> None:
        """Move the objective changer to a slot (1-based) and wait."""
        ...

    async def aobjective_home(self) -> None:
        """Home the objective changer and wait."""
        ...

    async def aobjective_status(self) -> dict[str, Any]:
        """Read the objective changer status (current slot, homed, ...)."""
        ...

    # -- illumination (raw PWM counts) ----------------------------------------

    async def aset_laser(self, channel: int, value: int) -> None:
        """Set a laser/LED PWM channel to a raw hardware value."""
        ...

    async def aled_fill(self, r: int, g: int, b: int) -> None:
        """Fill the LED matrix with a uniform colour."""
        ...

    async def aled_off(self) -> None:
        """Turn the LED matrix off."""
        ...

    # -- galvo (DAC counts) ----------------------------------------------------

    async def agalvo_goto(self, x: int, y: int) -> None:
        """Move the galvo mirror to an absolute XY position."""
        ...

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
        """Configure and start a raster scan."""
        ...

    async def agalvo_stop(self) -> None:
        """Stop any active galvo scan."""
        ...

    async def agalvo_status(self) -> dict[str, Any]:
        """Read the galvo status flags."""
        ...

    # -- events -----------------------------------------------------------------

    def subscribe(self) -> AsyncIterator[UC2Event]:
        """Yield typed hardware events; multiple concurrent consumers are allowed."""
        ...
