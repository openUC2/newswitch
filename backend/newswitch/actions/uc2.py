"""A UC2 board: pumping its bus, mirroring its events, and its own commands (per-axis homing and stopping, the LED matrix, node discovery, objective homing, the galvo scanner)."""

from dataclasses import dataclass
from typing import Optional

from arkitekt import Task
from koil import unkoil

from newswitch.drivers.uc2.dispatch import dispatch_uc2_events
from newswitch.models.uc2 import STAGE_AXES
from newswitch.protocols.uc2 import UC2BusManager
from newswitch.states.stage import StageState
from newswitch.states.uc2 import UC2State


async def run_uc2_bus(uc2_bus: UC2BusManager) -> None:
    """Connect the UC2 hardware bus and pump its transport until shutdown."""
    await uc2_bus.abackground()


async def run_uc2_event_dispatch(
    uc2_bus: UC2BusManager,
    stage_state: StageState,
    uc2_state: UC2State,
) -> None:
    """Mirror spontaneous UC2 hardware events into the shared reactive states."""
    await dispatch_uc2_events(uc2_bus, stage_state, uc2_state)


@dataclass
class GalvoStatus:
    """Decoded galvo scanner status flags."""

    raw: int = 0
    moving: bool = False
    scan_active: bool = False
    scan_complete: bool = False
    error: bool = False


def home_stage(uc2_bus: UC2BusManager, task: Task, axes: Optional[list[str]] = None) -> None:
    """Home stage axes sequentially in a mechanically safe order (Z first).

    Args:
        axes: Axes to home (subset of X/Y/Z/A). Default: Z, X, Y.
    """
    order = [axis.upper() for axis in (axes or ["Z", "X", "Y"])]
    for index, axis in enumerate(order):
        if axis not in STAGE_AXES:
            raise ValueError(f"Unknown axis {axis!r}; expected one of {STAGE_AXES}")
        task.progress(int(index / len(order) * 100), f"homing {axis}")
        unkoil(uc2_bus.ahome_axis, axis)
    task.progress(100, "homed")


def stop_stage(uc2_bus: UC2BusManager, axis: Optional[str] = None) -> None:
    """Immediately stop one stage axis (or all axes when none is given).

    Deliberately lock-free so it works while a move holds the stage lock.
    """
    targets = [axis.upper()] if axis else list(STAGE_AXES)
    for target in targets:
        unkoil(uc2_bus.astop_axis, target)


def led_matrix_fill(uc2_bus: UC2BusManager, r: int = 255, g: int = 255, b: int = 255) -> None:
    """Fill the LED matrix with a uniform colour (0-255 per channel)."""
    unkoil(uc2_bus.aled_fill, r, g, b)


def led_matrix_off(uc2_bus: UC2BusManager) -> None:
    """Turn the LED matrix off."""
    unkoil(uc2_bus.aled_off)


def uc2_scan_nodes(uc2_bus: UC2BusManager, uc2_state: UC2State, timeout: float = 3.0) -> list[int]:
    """Discover reachable UC2 bus nodes; the result also lands in UC2State."""
    return unkoil(uc2_bus.ascan_nodes, timeout)


def home_objective(uc2_bus: UC2BusManager) -> None:
    """Home the objective changer."""
    unkoil(uc2_bus.aobjective_home)


def galvo_set_position(uc2_bus: UC2BusManager, x: int, y: int) -> None:
    """Move the galvo mirror to an absolute XY position (DAC counts)."""
    unkoil(uc2_bus.agalvo_goto, x, y)


def galvo_raster_scan(
    uc2_bus: UC2BusManager,
    x_min: int = 500,
    x_max: int = 3500,
    y_min: int = 500,
    y_max: int = 3500,
    nx: int = 256,
    ny: int = 256,
    pixel_dwell_us: int = 1,
    trigger_mode: int = 1,
    bidirectional: bool = False,
) -> None:
    """Configure and start a galvo raster scan (camera trigger per pixel by default)."""
    unkoil(
        uc2_bus.agalvo_raster,
        x_min,
        x_max,
        y_min,
        y_max,
        nx,
        ny,
        pixel_dwell_us,
        trigger_mode,
        bidirectional,
    )


def galvo_stop(uc2_bus: UC2BusManager) -> None:
    """Stop any active galvo scan (lock-free so it works mid-scan)."""
    unkoil(uc2_bus.agalvo_stop)


def galvo_get_status(uc2_bus: UC2BusManager) -> GalvoStatus:
    """Read decoded galvo status flags (moving, scan_active, error, ...)."""
    status = unkoil(uc2_bus.agalvo_status)
    return GalvoStatus(
        raw=int(status.get("raw", 0)),
        moving=bool(status.get("moving", False)),
        scan_active=bool(status.get("scan_active", False)),
        scan_complete=bool(status.get("scan_complete", False)),
        error=bool(status.get("error", False)),
    )
