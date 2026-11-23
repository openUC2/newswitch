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

from typing import TYPE_CHECKING, Any, AsyncIterator, Optional, Protocol, runtime_checkable

from newswitch.instrument.hardware import Firmware
from newswitch.models.uc2 import UC2Event, UC2Node
from newswitch.protocols.base import BackgroundManager
from newswitch.states.uc2 import UC2State

if TYPE_CHECKING:  # pragma: no cover
    from newswitch.drivers.uc2.firmware import FirmwareImage, Report

# ---------------------------------------------------------------------------
# Typed hardware events
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Bus protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class UC2BusManager(BackgroundManager, Protocol):
    """Protocol for transport backends driving openUC2 hardware.

    Implementations: ``UC2CanBus`` (CANopen, preferred), ``UC2RestBus``
    (JSON-over-serial via uc2rest), ``VirtualUC2Bus`` (simulation).
    ``abackground()`` (from BackgroundManager) owns connect + event pumping.
    """

    state: UC2State
    firmware: Optional[Firmware]
    has_port_board: bool
    """Whether a board is on a port (the master over USB); on socketcan there are CAN nodes only."""
    """What the description says the board and its CAN nodes run; None: it says nothing."""

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

    async def ascan_nodes(self, timeout: float = 3.0) -> list[UC2Node]:
        """The reachable CAN nodes, each as it identifies itself (image, version, build, MAC)."""
        ...

    async def aidentify(self) -> Optional[UC2Node]:
        """The board on the port, as it identifies itself; None when there is none (socketcan)."""
        ...

    # -- firmware (`newswitch.drivers.uc2.firmware`) -----------------------------

    async def aflash_board(self, image: "FirmwareImage", report: "Report") -> None:
        """Write `image` to the board on the port over USB, and reconnect to it."""
        ...

    async def aflash_node(self, can_id: int, image: "FirmwareImage", report: "Report") -> None:
        """Send `image` (the app alone) to a CAN node, which reboots into it."""
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

    async def aset_laser(self, channel: int, value: int, node: Optional[int] = None) -> None:
        """Set a laser/LED PWM channel to a raw hardware value. `node`: the CAN node it is on, for
        a bus that addresses nodes itself (canopen); a master routes channels on its own."""
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
