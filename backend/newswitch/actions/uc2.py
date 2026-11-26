"""A UC2 board's own: pumping its bus, mirroring its events, what is on its bus and its firmware,
and its galvo scanner. Each names the board (`BoardName`), chosen from those the microscope has.

What a board moves, swaps or lights is a variable, driven like any other through `Values`
(`newswitch.actions.values`: ``home_stage``, ``stop_stage``, ``home_objective``, ``tune``).
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from arkitekt import Task
from koil import unkoil

from newswitch.drivers.uc2 import firmware
from newswitch.drivers.uc2.boards import BoardName, UC2Boards
from newswitch.drivers.uc2.dispatch import dispatch_uc2_events
from newswitch.models.uc2 import UC2Node
from newswitch.protocols.uc2 import UC2BusManager
from newswitch.services.values import Values
from newswitch.states.uc2 import UC2State

logger = logging.getLogger(__name__)


async def run_uc2_bus(uc2: UC2Boards) -> None:
    """Connect every board's bus and pump it until shutdown."""
    await uc2.abackground()


async def keep_firmware(uc2: UC2Boards, uc2_state: UC2State) -> None:
    """On start, on real hardware: read what each board and its CAN nodes run, and compare it with
    what the description pins (``boards.<board>.firmware``). As its ``on_start`` says, flash what
    differs (``flash``: each image fetched and checked first, then the board, then the nodes), or
    only say so in UC2State (``check``). A failure is said there too; the server runs on."""
    await asyncio.gather(*(_keep_firmware(bus, uc2_state) for bus in uc2))


async def _keep_firmware(uc2_bus: UC2BusManager, uc2_state: UC2State) -> None:
    spec = uc2_bus.firmware
    if spec is None or spec.on_start == "off" or not uc2_bus.keeps_firmware:
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


async def run_uc2_event_dispatch(uc2: UC2Boards, values: Values, uc2_state: UC2State) -> None:
    """Mirror every board's spontaneous hardware events into the shared reactive states."""
    await asyncio.gather(*(dispatch_uc2_events(bus, values, uc2_state) for bus in uc2))


@dataclass
class GalvoStatus:
    """Decoded galvo scanner status flags."""

    raw: int = 0
    moving: bool = False
    scan_active: bool = False
    scan_complete: bool = False
    error: bool = False


def uc2_scan_nodes(
    uc2: UC2Boards, uc2_state: UC2State, board: BoardName, timeout: float = 3.0
) -> list[UC2Node]:
    """What is on a board's bus: the CAN nodes, each with the image and version it runs (and the
    env the description wants). The board on the port and the nodes also land in UC2State.

    Args:
        board: The board.
        timeout: How long to listen for nodes, in seconds.
    """
    _, nodes = unkoil(firmware.scan, uc2[board], uc2_state, timeout)
    return nodes


async def update_firmware(
    uc2: UC2Boards,
    uc2_state: UC2State,
    task: Task,
    board: BoardName,
    nodes: Optional[list[int]] = None,
    port_board: bool = True,
    full: bool = False,
    force: bool = False,
) -> list[UC2Node]:
    """Flash the firmware the description names (``boards.<board>.firmware``) where it is not
    running yet: the board on the port over USB first, then each CAN node through the bus. A
    flashed board counts once it reports its new image. The bus is down meanwhile.

    Args:
        board: The board.
        nodes: Only these CAN nodes (each needs an env in the description); default: all it names.
        port_board: Flash the board on the port too.
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
        uc2[board],
        uc2_state,
        only=nodes,
        with_board=port_board,
        full=full,
        force=force,
        report=report,
    )


def galvo_set_position(uc2: UC2Boards, board: BoardName, x: int, y: int) -> None:
    """Move a board's galvo mirror to an absolute XY position (DAC counts)."""
    unkoil(uc2[board].agalvo_goto, x, y)


def galvo_raster_scan(
    uc2: UC2Boards,
    board: BoardName,
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
        uc2[board].agalvo_raster,
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


def galvo_stop(uc2: UC2Boards, board: BoardName) -> None:
    """Stop any active galvo scan (lock-free so it works mid-scan)."""
    unkoil(uc2[board].agalvo_stop)


def galvo_get_status(uc2: UC2Boards, board: BoardName) -> GalvoStatus:
    """Read decoded galvo status flags (moving, scan_active, error, ...)."""
    status = unkoil(uc2[board].agalvo_status)
    return GalvoStatus(
        raw=int(status.get("raw", 0)),
        moving=bool(status.get("moving", False)),
        scan_active=bool(status.get("scan_active", False)),
        scan_complete=bool(status.get("scan_complete", False)),
        error=bool(status.get("error", False)),
    )
