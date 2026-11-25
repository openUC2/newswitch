"""A UC2 board: pumping its bus, mirroring its events, and its own commands (per-axis homing and stopping, the LED matrix, what is on the bus and its firmware, objective homing, the galvo scanner)."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from arkitekt import Task
from koil import unkoil

from newswitch.drivers.uc2 import firmware
from newswitch.drivers.uc2.actuators import Turret
from newswitch.drivers.uc2.dispatch import dispatch_uc2_events
from newswitch.models.uc2 import STAGE_AXES, UC2Node
from newswitch.protocols.uc2 import UC2BusManager
from newswitch.services.values import Values
from newswitch.simulation.uc2_bus import VirtualUC2Bus
from newswitch.states.uc2 import UC2State

logger = logging.getLogger(__name__)


async def run_uc2_bus(uc2_bus: UC2BusManager) -> None:
    """Connect the UC2 hardware bus and pump its transport until shutdown."""
    await uc2_bus.abackground()


async def keep_firmware(uc2_bus: UC2BusManager, uc2_state: UC2State) -> None:
    """On start, on real hardware: read what the board and each CAN node run, and compare it with
    what the description pins (``boards.<board>.firmware``). As its ``on_start`` says, flash what
    differs (``flash``: each image fetched and checked first, then the board, then the nodes), or
    only say so in UC2State (``check``). A failure is said there too; the server runs on."""
    spec = uc2_bus.firmware
    if spec is None or spec.on_start == "off" or isinstance(uc2_bus, VirtualUC2Bus):
        return
    try:
        if spec.on_start == "check":
            board, nodes = await firmware.scan(uc2_bus, uc2_state)
            jobs = firmware.plan(spec, board, nodes, with_board=uc2_bus.has_port_board)
            if jobs:
                uc2_state.last_error = "firmware: " + "; ".join(f"{j.target} {j.why}" for j in jobs)
                logger.warning("UC2 %s", uc2_state.last_error)
            return
        await firmware.update(uc2_bus, uc2_state)
        pinned = len(spec.nodes) + (spec.board is not None and uc2_bus.has_port_board)
        logger.info("UC2 firmware: the %d pinned boards run what the description pins", pinned)
    except Exception as exc:  # the bus is unreachable, or a pinned build cannot be had
        uc2_state.last_error = f"firmware: {exc}"
        logger.error("UC2 firmware not brought to the description: %s", exc)


async def run_uc2_event_dispatch(
    uc2_bus: UC2BusManager,
    values: Values,
    uc2_state: UC2State,
) -> None:
    """Mirror spontaneous UC2 hardware events into the shared reactive states."""
    await dispatch_uc2_events(uc2_bus, values, uc2_state)


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

    Deliberately lock-free so it works while a move holds the motion lock.
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


def uc2_scan_nodes(
    uc2_bus: UC2BusManager, uc2_state: UC2State, timeout: float = 3.0
) -> list[UC2Node]:
    """What is on the bus: the CAN nodes, each with the image and version it runs (and the env the
    description wants). The board on the port and the nodes also land in UC2State.

    Args:
        timeout: How long to listen for nodes, in seconds.
    """
    _, nodes = unkoil(firmware.scan, uc2_bus, uc2_state, timeout)
    return nodes


async def update_firmware(
    uc2_bus: UC2BusManager,
    uc2_state: UC2State,
    task: Task,
    nodes: Optional[list[int]] = None,
    board: bool = True,
    full: bool = False,
    force: bool = False,
) -> list[UC2Node]:
    """Flash the firmware the description names (``boards.<board>.firmware``) where it is not
    running yet: the board on the port over USB first, then each CAN node through the bus. A
    flashed board counts once it reports its new image. The bus is down meanwhile.

    Args:
        nodes: Only these CAN nodes (each needs an env in the description); default: all it names.
        board: Flash the board on the port too.
        full: Write the board's merged image (bootloader and partitions), as for a blank board. It
            resets what the board stored: its node id, role and positions.
        force: Flash even what already runs the wanted image.
    """
    sent: set[asyncio.Task[None]] = set()

    def report(message: str, percent: int) -> None:
        progress = asyncio.ensure_future(task.aprogress(percent, message))
        sent.add(progress)
        progress.add_done_callback(sent.discard)

    return await firmware.update(
        uc2_bus,
        uc2_state,
        only=nodes,
        with_board=board,
        full=full,
        force=force,
        report=report,
    )


def home_objective(uc2_bus: UC2BusManager, values: Values) -> None:
    """Home the objective changer, which leaves it at its first slot."""
    unkoil(uc2_bus.aobjective_home)
    for name, driver in values.drivers.items():
        if isinstance(driver, Turret):
            slots = values.instrument.variables[name].slots
            values.stepped(name, min(slots))


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
