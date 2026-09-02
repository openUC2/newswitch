"""Registered functions exposing the UC2 hardware bus (Wave-1 surface).

Complements the core stage/illumination actions in ``newswitch.app`` with
per-axis homing/stopping, LED-matrix control, CAN node discovery, objective
homing, and the galvo scanner. Importing this module registers everything on
the default app registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from koil import unkoil
from rekuest_next import model, progress
from rekuest_next.register import register

from newswitch.protocols.uc2 import STAGE_AXES, UC2BusManager, UC2State


@model
@dataclass
class GalvoStatus:
    """Decoded galvo scanner status flags."""

    raw: int = 0
    moving: bool = False
    scan_active: bool = False
    scan_complete: bool = False
    error: bool = False


@register(locks=["stage_position"])
def home_stage(uc2_bus: UC2BusManager, axes: Optional[list[str]] = None) -> None:
    """Home stage axes sequentially in a mechanically safe order (Z first).

    Args:
        axes: Axes to home (subset of X/Y/Z/A). Default: Z, X, Y.
    """
    order = [axis.upper() for axis in (axes or ["Z", "X", "Y"])]
    for index, axis in enumerate(order):
        if axis not in STAGE_AXES:
            raise ValueError(f"Unknown axis {axis!r}; expected one of {STAGE_AXES}")
        progress(int(index / len(order) * 100), f"homing {axis}")
        unkoil(uc2_bus.ahome_axis, axis)
    progress(100, "homed")


@register
def stop_stage(uc2_bus: UC2BusManager, axis: Optional[str] = None) -> None:
    """Immediately stop one stage axis (or all axes when none is given).

    Deliberately lock-free so it works while a move holds the stage lock.
    """
    targets = [axis.upper()] if axis else list(STAGE_AXES)
    for target in targets:
        unkoil(uc2_bus.astop_axis, target)


@register(locks=["illumination"])
def led_matrix_fill(uc2_bus: UC2BusManager, r: int = 255, g: int = 255, b: int = 255) -> None:
    """Fill the LED matrix with a uniform colour (0-255 per channel)."""
    unkoil(uc2_bus.aled_fill, r, g, b)


@register(locks=["illumination"])
def led_matrix_off(uc2_bus: UC2BusManager) -> None:
    """Turn the LED matrix off."""
    unkoil(uc2_bus.aled_off)


@register
def uc2_scan_nodes(uc2_bus: UC2BusManager, uc2_state: UC2State, timeout: float = 3.0) -> list[int]:
    """Discover reachable UC2 bus nodes; the result also lands in UC2State."""
    return unkoil(uc2_bus.ascan_nodes, timeout)


@register(locks=["objective"])
def home_objective(uc2_bus: UC2BusManager) -> None:
    """Home the objective changer."""
    unkoil(uc2_bus.aobjective_home)


@register(locks=["galvo"])
def galvo_set_position(uc2_bus: UC2BusManager, x: int, y: int) -> None:
    """Move the galvo mirror to an absolute XY position (DAC counts)."""
    unkoil(uc2_bus.agalvo_goto, x, y)


@register(locks=["galvo"])
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


@register
def galvo_stop(uc2_bus: UC2BusManager) -> None:
    """Stop any active galvo scan (lock-free so it works mid-scan)."""
    unkoil(uc2_bus.agalvo_stop)


@register
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
