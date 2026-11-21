"""What is on a UC2 bus, and bringing its firmware to what the description names.

    just uc2 scan                                   # the board on the port and the CAN nodes
    just uc2 status                                 # ... against the firmware the description names
    just uc2 flash --dry-run                        # what would be flashed, from where
    just uc2 flash [--node 11 ...] [--no-board] [--full] [--force] [--yes]
    just uc2 scan --port /dev/ttyUSB0 --transport rest --baudrate 921600   # without a description

The board and its firmware (``hardware.boards.<board>.firmware``) come from the description
``NEWSWITCH_CONFIG`` names; ``--port`` / ``--transport`` override it, or stand in for it. This talks to
the port directly, so nothing else may hold it (stop a running server first; a running agent has the
same as actions: ``uc2_scan_nodes``, ``update_firmware``). What is flashed and how:
`newswitch.drivers.uc2.firmware`.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import sys
from typing import Optional

from newswitch.drivers.uc2 import firmware as fw
from newswitch.drivers.uc2.canopen_bus import UC2CanBus, UC2CanBusConfig
from newswitch.drivers.uc2.rest_bus import UC2RestBus, UC2RestBusConfig
from newswitch.drivers.uc2.virtual_bus import VirtualUC2Bus
from newswitch.instrument.hardware import Firmware
from newswitch.models.uc2 import UC2Node
from newswitch.protocols.uc2 import UC2BusManager
from newswitch.settings import CONFIG_ENV_VAR
from newswitch.states.uc2 import UC2State

#: What the node map of a CAN bus expects each node to be.
_EXPECTED_KINDS = {
    "node_x": "motor",
    "node_y": "motor",
    "node_z": "motor",
    "node_a": "motor",
    "node_led": "led",
    "node_laser": "laser",
    "node_galvo": "galvo",
}


def _bus_of(args: argparse.Namespace) -> UC2BusManager:
    """The real bus: the description's board, with what the command line overrides."""
    state = UC2State()
    firmware: Optional[Firmware] = None
    if os.environ.get(CONFIG_ENV_VAR) and not args.no_description:
        from newswitch.microscope.parts import build_uc2_bus
        from newswitch.settings import load_devices, load_settings

        settings = load_settings()
        instrument = load_devices(settings)
        if instrument is not None and instrument.hardware.board is not None:
            board = instrument.hardware.board
            if args.simulate:
                return VirtualUC2Bus(state, firmware=board.firmware)
            if args.transport in (None, board.transport):
                real = settings.model_copy(update={"simulate": "nothing"})
                bus = build_uc2_bus(real, instrument, state)
                if args.port:
                    if isinstance(bus, UC2RestBus):
                        bus.config.serialport = args.port
                    elif isinstance(bus, UC2CanBus):
                        bus.config.port = args.port
                if args.baudrate and isinstance(bus, UC2RestBus):
                    bus.config.baudrate = args.baudrate
                return bus
            firmware = board.firmware
    if args.simulate:
        return VirtualUC2Bus(state, firmware=firmware)
    if (args.transport or "rest") == "rest":
        config = UC2RestBusConfig(serialport=args.port, baudrate=args.baudrate or 921600)
        return UC2RestBus(state, config, firmware=firmware)
    can = UC2CanBusConfig(
        interface="waveshare" if args.port else "socketcan",
        channel=None if args.port else (args.channel or "can0"),
        port=args.port,
    )
    return UC2CanBus(state, can, firmware=firmware)


def _row(node: UC2Node, firmware: Optional[Firmware], board: bool = False) -> str:
    pin = None if firmware is None else firmware.pin_for(None if board else node.can_id)
    wanted = f"{node.wanted} {node.wanted_version}" if node.wanted else "-"
    mark = (
        "" if pin is None or firmware is None else ("ok" if fw.runs(node, pin, firmware) else "OLD")
    )
    return (
        f"  {node.can_id:>4}  {node.kind or '?':<10} {node.status or '':<11} "
        f"{node.image or '?':<52} {node.firmware or '?':<22} {node.build or '':<22} "
        f"{node.mac or '':<17}  {wanted} {mark}"
    ).rstrip()


def _print(bus: UC2BusManager, board: Optional[UC2Node], nodes: list[UC2Node]) -> None:
    release = bus.firmware.release if bus.firmware is not None else None
    print(f"release: {release or '(the description names no firmware)'}")
    print(
        f"  {'node':>4}  {'kind':<10} {'status':<11} {'image':<52} {'version':<22} {'build':<22} {'mac':<17}  wanted"
    )
    if board is not None:
        print(_row(board, bus.firmware, board=True) + "   <- the board on the port")
    for node in nodes:
        print(_row(node, bus.firmware))
    if not nodes:
        print("  (no CAN node answered)")


def _node_map_problems(bus: UC2BusManager, nodes: list[UC2Node]) -> list[str]:
    """Where the bus's node map disagrees with what the nodes say they are."""
    if not isinstance(bus, UC2CanBus):
        return []
    kinds = {node.can_id: node.kind for node in nodes}
    problems = []
    for field, kind in _EXPECTED_KINDS.items():
        can_id = getattr(bus.config, field)
        found = kinds.get(can_id)
        if found and found != kind:
            problems.append(f"{field} is {can_id}, but node {can_id} is a {found}, not a {kind}")
    return problems


async def _connected(bus: UC2BusManager, timeout: float) -> asyncio.Task[None]:
    task = asyncio.ensure_future(bus.abackground())
    for _ in range(int(timeout * 10)):
        if bus.state.connected:
            return task
        if task.done():
            task.result()
        await asyncio.sleep(0.1)
    task.cancel()
    raise SystemExit(
        f"no UC2 board answered within {timeout:.0f} s: {bus.state.last_error or 'no error'}"
    )


async def _run(args: argparse.Namespace) -> int:
    bus = _bus_of(args)
    pump = await _connected(bus, args.connect_timeout)
    try:
        board, nodes = await fw.scan(bus, bus.state, args.timeout)
        if args.command in ("scan", "status"):
            _print(bus, board, nodes)
            for problem in _node_map_problems(bus, nodes) if args.command == "status" else []:
                print(f"! {problem}")
            return 0
        if bus.firmware is None:
            raise SystemExit("the description names no firmware: set boards.<board>.firmware")
        jobs = fw.plan(
            bus.firmware,
            board,
            nodes,
            only=args.node or None,
            with_board=not args.no_board,
            force=args.force,
        )
        _print(bus, board, nodes)
        if not jobs:
            print("\nnothing to flash: everything runs what the description names")
            return 0
        print("\nto flash, in this order:")
        for job in jobs:
            full = args.full and job.can_id is None
            how = (
                "USB, merged image at 0x0 (resets NVS)"
                if full
                else (
                    "USB, app at 0x10000 (keeps NVS)"
                    if job.can_id is None
                    else "CAN OTA (keeps NVS)"
                )
            )
            print(
                f"  {job.target:<10} {job.env:<42} {how}\n             {fw.image_url(bus.firmware, job.pin, full)}\n             why: {job.why}"
            )
        if args.dry_run:
            return 0
        if not args.yes and input("\nflash now? [y/N] ").strip().lower() not in ("y", "yes"):
            print("not flashed")
            return 1

        def report(message: str, percent: int) -> None:
            print(f"\r  [{percent:3d} %] {message:<90}", end="", flush=True)

        nodes = await fw.update(
            bus,
            bus.state,
            only=args.node or None,
            with_board=not args.no_board,
            full=args.full,
            force=args.force,
            report=report,
        )
        print("\n\nflashed; the bus now reports:")
        _print(bus, bus.state.board, nodes)
        return 0
    finally:
        pump.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await pump


def main(argv: list[str] | None = None) -> None:
    """Command line: ``python -m newswitch.tools.uc2 scan|status|flash``."""
    parser = argparse.ArgumentParser(
        prog="python -m newswitch.tools.uc2",
        description="What is on a UC2 bus, and flashing the firmware the description names.",
    )
    parser.add_argument("command", choices=["scan", "status", "flash"])
    parser.add_argument(
        "--port", help="the serial port (rest), or a Waveshare USB-CAN port (canopen)"
    )
    parser.add_argument(
        "--transport", choices=["rest", "canopen"], help="default: the description's"
    )
    parser.add_argument("--baudrate", type=int, help="of the serial link (rest; HAT+: 921600)")
    parser.add_argument("--channel", help="the socketcan interface (canopen; default can0)")
    parser.add_argument("--no-description", action="store_true", help=f"ignore ${CONFIG_ENV_VAR}")
    parser.add_argument("--timeout", type=float, default=3.0, help="how long to scan, in seconds")
    parser.add_argument("--connect-timeout", type=float, default=20.0)
    parser.add_argument(
        "--node", type=int, action="append", help="flash only this CAN node (repeat)"
    )
    parser.add_argument("--no-board", action="store_true", help="leave the board on the port alone")
    parser.add_argument("--full", action="store_true", help="the board's merged image (resets NVS)")
    parser.add_argument("--force", action="store_true", help="flash what already runs it too")
    parser.add_argument(
        "--dry-run", action="store_true", help="say what would be flashed, and stop"
    )
    parser.add_argument("--yes", action="store_true", help="do not ask before flashing")
    parser.add_argument("--simulate", action="store_true", help="a simulated bus (no hardware)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
