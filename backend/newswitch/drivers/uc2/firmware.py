"""The firmware of a UC2 bus: what each board runs, what the description wants, and flashing it.

A description names a release of the UC2 firmware and the PlatformIO env of each board
(`newswitch.instrument.hardware.Firmware`). A release publishes two images per env
(``<source>/<release>/esp32_<env>.bin`` and ``…_merged.bin``):

- the app alone, which keeps what the board stored (NVS: its node id, role, positions). Over USB it
  is written at 0x10000; over CAN the satellite writes it into its free OTA slot;
- the merged image, bootloader and partitions included, written at 0x0 over USB only. It resets
  NVS: for a blank board (``full``).

`update` brings a bus to what its description wants, in the documented order: the board on the port
over USB (esptool) first, then each CAN node through it (or directly on socketcan). A node reboots
into its new firmware by itself; a board counts as updated once it reports the image it was flashed
from. The transports do the writing (`UC2BusManager.aflash_board`, ``aflash_node``); this module
decides what, fetches it, and checks the result. What they report is parsed here too
(`node_from_scan`, `board_from_state`), so both transports describe a board the same way.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import struct
import sys
import urllib.request
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from newswitch.instrument.hardware import Firmware, FirmwarePin
from newswitch.models.uc2 import UC2Node

if TYPE_CHECKING:  # pragma: no cover
    from newswitch.protocols.uc2 import UC2BusManager
    from newswitch.states.uc2 import UC2State

logger = logging.getLogger(__name__)

#: Reports progress: what is happening, and how far (0-100) it is.
Report = Callable[[str, int], None]

#: The first byte of an ESP image.
ESP_IMAGE_MAGIC = 0xE9
#: Where the app goes when it is written alone over USB (the merged image goes to 0x0).
APP_OFFSET = 0x10000
#: The chip an image is for: its header's chip id (esp-idf ``esp_chip_id_t``) -> esptool's name.
CHIP_IDS = {0x0000: "esp32", 0x0002: "esp32s2", 0x0005: "esp32c3", 0x0009: "esp32s3"}
#: How fast esptool writes over USB (the HAT+'s CP2102 takes 921600).
FLASH_BAUD = 921600
#: How long a flashed board may take to come back and report its new image.
VERIFY_TIMEOUT_S = 60.0


def _cache_root() -> Path:
    return (
        Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "newswitch" / "firmware"
    )


# --- what a board reports ---------------------------------------------------------------------


def _text(value: Any) -> str:  # noqa: ANN401 - a firmware reply's value, of any type
    return "" if value is None else str(value)


def _kind_of_image(image: str) -> str:
    """What a board is, from the image it runs (``…slave_motor…`` is a motor)."""
    found = re.search(r"(master|standalone|slave_([a-z]+)|bridge_([a-z0-9]+))", image)
    if found is None:
        return ""
    return found.group(2) or (f"bridge {found.group(3)}" if found.group(3) else found.group(1))


def node_from_scan(entry: Mapping[str, Any], wanted: Optional[str] = None) -> UC2Node:
    """A node of the master's CAN scan (``/can_act {"scan": true}``), e.g.
    ``{"canId": 11, "deviceTypeStr": "motor", "statusStr": "idle", "fwVersion": "…",
    "fwImage": "esp32_UC2_canopen_slave_motor_release_motX.bin", "build": "…", "mac": "…"}``."""
    image = _text(entry.get("fwImage"))
    return UC2Node(
        can_id=int(entry["canId"]),
        kind=_text(entry.get("deviceTypeStr")) or _kind_of_image(image),
        status=_text(entry.get("statusStr")),
        firmware=_text(entry.get("fwVersion")),
        image=image,
        build=_text(entry.get("build")),
        mac=_text(entry.get("mac")),
        wanted=wanted,
    )


def scan_entries(reply: Any) -> tuple[Optional[Mapping[str, Any]], list[Mapping[str, Any]]]:  # noqa: ANN401
    """The master and the nodes of a scan reply: a ``{"master": …, "scan": […]}`` dict, or a list
    of replies holding one."""
    replies = reply if isinstance(reply, (list, tuple)) else [reply]
    for candidate in replies:
        if isinstance(candidate, Mapping) and "scan" in candidate:
            nodes = [
                n for n in candidate.get("scan") or [] if isinstance(n, Mapping) and "canId" in n
            ]
            master = candidate.get("master")
            return (master if isinstance(master, Mapping) else None), nodes
    return None, []


def board_from_state(
    reply: Any, wanted: Optional[str] = None, can_id: int = 1
) -> Optional[UC2Node]:  # noqa: ANN401
    """The board on the port, from its ``/state_get`` reply: ``{"state": {"identifier_version": …,
    "identifier_image": "esp32_UC2_canopen_master_release.bin", "pindef": …, …}}``; None if it
    says nothing of itself."""
    replies = reply if isinstance(reply, (list, tuple)) else [reply]
    for candidate in replies:
        if not isinstance(candidate, Mapping):
            continue
        state = candidate.get("state", candidate)
        if not isinstance(state, Mapping) or not any(k.startswith("identifier_") for k in state):
            continue
        image = _text(state.get("identifier_image"))
        pindef = _text(state.get("pindef"))
        return UC2Node(
            can_id=can_id,
            kind=_kind_of_image(image)
            or _kind_of_image(pindef)
            or _text(state.get("identifier_name")),
            status="connected",
            firmware=_text(state.get("identifier_version") or state.get("identifier_id")),
            image=image,
            build=_text(state.get("identifier_date")),
            mac=_text(state.get("mac")),
            wanted=wanted,
        )
    return None


def wanting(node: UC2Node, firmware: Optional[Firmware], board: bool = False) -> UC2Node:
    """`node`, with what `firmware` pins it to (the board on the port with `board`)."""
    pin = None if firmware is None else firmware.pin_for(None if board else node.can_id)
    if pin is None or firmware is None:
        return node
    return replace(node, wanted=pin.env, wanted_version=firmware.version_of(pin))


def image_name(env: str) -> str:
    """The file an env's app image is published as."""
    return f"esp32_{env}.bin"


def runs(node: UC2Node, pin: FirmwarePin, firmware: Firmware) -> bool:
    """Whether `node` runs what `pin` says: the image it reports is the env's, and its version the
    pinned one (the release's tag, unless the pin names a build). A release image reports exactly its
    tag (``v2026.0.0-beta.4``); a development build what ``git describe`` said
    (``v2026.0.0-beta.4-13-ge86ebf3-t…``). A firmware that reports no version counts by its image."""
    image = Path(node.image).name
    if image not in (image_name(pin.env), f"esp32_{pin.env}_merged.bin"):
        return False
    return not node.firmware or node.firmware.strip() == firmware.version_of(pin)


# --- what is to be flashed ------------------------------------------------------------------


@dataclass(frozen=True)
class Job:
    """One board to flash: the board on the port (``can_id`` None) or a CAN node, and its pin."""

    can_id: Optional[int]
    pin: FirmwarePin
    version: str
    why: str

    @property
    def env(self) -> str:
        """The env it is to run."""
        return self.pin.env

    @property
    def target(self) -> str:
        """What is flashed, in words."""
        return "the board" if self.can_id is None else f"node {self.can_id}"


def plan(
    firmware: Firmware,
    board: Optional[UC2Node],
    nodes: Iterable[UC2Node],
    *,
    only: Optional[Iterable[int]] = None,
    with_board: bool = True,
    force: bool = False,
) -> list[Job]:
    """What to flash, board first: each board the description pins that runs something else (or
    each, with `force`). `only` limits the CAN nodes; a node it names must be on the bus and be
    pinned.

    Raises:
        ValueError: `only` names a node the description does not pin, or that is not on the bus.
    """
    found = {node.can_id: node for node in nodes}
    jobs: list[Job] = []
    if with_board and firmware.board is not None:
        if board is None:
            raise ValueError("the board on the port did not identify itself: is it connected?")
        if force or not runs(board, firmware.board, firmware):
            jobs.append(_job(None, board, firmware.board, firmware, force))
    targets = sorted(firmware.nodes) if only is None else sorted(set(only))
    for can_id in targets:
        if can_id not in firmware.nodes:
            raise ValueError(f"the description names no firmware for node {can_id}")
        pin = firmware.nodes[can_id]
        node = found.get(can_id)
        if node is None:
            if only is not None:
                raise ValueError(f"node {can_id} is not on the bus")
            logger.warning("node %s (%s) is not on the bus: not flashed", can_id, pin.env)
            continue
        if force or not runs(node, pin, firmware):
            jobs.append(_job(can_id, node, pin, firmware, force))
    return jobs


def _job(
    can_id: Optional[int], node: UC2Node, pin: FirmwarePin, firmware: Firmware, force: bool
) -> Job:
    version = firmware.version_of(pin)
    if force:
        why = "asked to"
    elif Path(node.image).name in (image_name(pin.env), f"esp32_{pin.env}_merged.bin"):
        why = f"runs {pin.env} {node.firmware or 'of an unknown version'}, not {version}"
    else:
        why = f"runs {node.image or 'an unknown image'}, not {pin.env}"
    return Job(can_id, pin, version, why)


# --- fetching -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class FirmwareImage:
    """An image, downloaded: where it is, the chip it is for, where it is written over USB, and the
    version it reports once it runs (read off its app descriptor)."""

    path: Path
    chip: str
    offset: int
    url: str
    version: str = ""


def image_url(firmware: Firmware, pin: FirmwarePin, full: bool = False) -> str:
    """Where an image of `pin` is published (the merged one with `full`)."""
    suffix = "_merged" if full else ""
    release = firmware.release_of(pin)
    return f"{firmware.source.rstrip('/')}/{release}/esp32_{pin.env}{suffix}.bin"


def chip_of(data: bytes) -> str:
    """The chip an ESP image is for, read off its header (at 0, or at 0x1000 for an ESP32's merged
    image, whose bootloader starts there).

    Raises:
        ValueError: It is no ESP image.
    """
    for start in (0, 0x1000):
        if len(data) >= start + 16 and data[start] == ESP_IMAGE_MAGIC:
            (chip_id,) = struct.unpack_from("<H", data, start + 12)
            return CHIP_IDS.get(chip_id, "auto")
    raise ValueError("not an ESP image: no 0xE9 magic byte at 0 or 0x1000")


#: The ESP-IDF app descriptor (``esp_app_desc_t``): after the app's image header, at +0x20.
APP_DESC_MAGIC = 0xABCD5432


def app_version(data: bytes, full: bool = False) -> str:
    """The version an image's app reports (its ``esp_app_desc_t``); "" if it has no descriptor.
    In a merged image the app starts at 0x10000."""
    start = (APP_OFFSET if full else 0) + 0x20
    if len(data) < start + 0x30 or struct.unpack_from("<I", data, start)[0] != APP_DESC_MAGIC:
        return ""
    return data[start + 0x10 : start + 0x30].split(b"\0", 1)[0].decode(errors="replace")


def _download(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    with urllib.request.urlopen(url, timeout=60) as response, open(partial, "wb") as out:  # noqa: S310 - https URL of the description
        while chunk := response.read(1 << 16):
            out.write(chunk)
    partial.replace(target)


async def fetch(
    firmware: Firmware, pin: FirmwarePin, full: bool = False, cache: Optional[Path] = None
) -> FirmwareImage:
    """An image of `pin`, from its release, downloaded once into the cache.

    Raises:
        ValueError: What was downloaded is no ESP image.
        urllib.error.URLError: The release has no such image, or cannot be reached.
    """
    url = image_url(firmware, pin, full)
    path = (cache or _cache_root()) / firmware.release_of(pin) / url.rsplit("/", 1)[1]
    if not path.exists():
        logger.info("downloading %s", url)
        await asyncio.to_thread(_download, url, path)
    data = await asyncio.to_thread(path.read_bytes)
    try:
        chip = chip_of(data)
    except ValueError:
        path.unlink(missing_ok=True)
        raise
    return FirmwareImage(
        path=path,
        chip=chip,
        offset=0 if full else APP_OFFSET,
        url=url,
        version=app_version(data, full),
    )


# --- flashing over USB ------------------------------------------------------------------------

_WRITING = re.compile(rb"Writing at 0x[0-9a-fA-F]+.*?\(\s*(\d+)\s*%\)")


async def esptool_flash(
    port: str, image: FirmwareImage, report: Optional[Report] = None, baud: int = FLASH_BAUD
) -> None:
    """Write `image` to the board on `port` with esptool (``python -m esptool``).

    The app alone keeps the flash's mode, frequency and size as the bootloader set them.

    Raises:
        RuntimeError: esptool failed; its output says why.
    """
    command = [sys.executable, "-m", "esptool", "--chip", image.chip, "--port", port]
    command += ["--baud", str(baud), "write-flash"]
    if image.offset != 0:
        command += ["--flash-mode", "keep", "--flash-freq", "keep", "--flash-size", "keep"]
    command += [hex(image.offset), str(image.path)]
    logger.info("flashing: %s", " ".join(command))
    process = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    assert process.stdout is not None
    output = bytearray()
    while chunk := await process.stdout.read(256):
        output += chunk
        if report is not None:
            percents = _WRITING.findall(bytes(output[-512:]))
            if percents:
                report(f"writing {image.path.name}", int(percents[-1]))
    if await process.wait() != 0:
        tail = bytes(output[-2000:]).decode(errors="replace")
        raise RuntimeError(f"esptool failed on {port}:\n{tail}")


# --- bringing a bus to what its description wants ---------------------------------------------


async def update(
    bus: "UC2BusManager",
    state: "UC2State",
    *,
    only: Optional[Iterable[int]] = None,
    with_board: bool = True,
    full: bool = False,
    force: bool = False,
    report: Optional[Report] = None,
    fetcher: Optional[Callable[[Firmware, FirmwarePin, bool], Awaitable[FirmwareImage]]] = None,
    verify_timeout: float = VERIFY_TIMEOUT_S,
) -> list[UC2Node]:
    """Flash what the bus's description pins and it does not run yet; the nodes, as they then
    report.

    Every image is fetched, and its version checked against the pin, before anything is written.
    Then the board on the port first (over USB), then each CAN node (through it, or on socketcan),
    then a rescan until each flashed one reports what it was pinned to.

    Raises:
        ValueError: The description names no firmware or a node it cannot flash, or an image is
            not the build it pins (a development build no release publishes, say).
        RuntimeError: Flashing failed, or a flashed board did not come back running its new image.
    """
    firmware = bus.firmware
    if firmware is None:
        raise ValueError("the description names no firmware: set boards.<board>.firmware")
    fetcher = fetcher or fetch

    def say(message: str, percent: int) -> None:
        state.flashing = f"{message} ({percent} %)"
        if report is not None:
            report(message, percent)

    board, nodes = await scan(bus, state)
    # On socketcan no board is on a port: only the CAN nodes are the bus's to flash.
    with_board = with_board and bus.has_port_board
    jobs = plan(firmware, board, nodes, only=only, with_board=with_board, force=force)
    if not jobs:
        state.flashing = None
        return nodes
    try:
        images: list[tuple[Job, FirmwareImage]] = []
        for job in jobs:
            say(f"{job.target} ({job.env}): downloading", 0)
            # A satellite takes the app alone; the board its merged image with `full`.
            image = await fetcher(firmware, job.pin, full and job.can_id is None)
            if image.version and image.version != job.version:
                raise ValueError(
                    f"{job.target} is pinned to {job.env} {job.version}, but {image.url} is "
                    f"{image.version}: set its release (or source) to where that build is"
                )
            images.append((job, image))
        for index, (job, image) in enumerate(images):
            base = int(index / len(jobs) * 90)

            def step(message: str, percent: int, job: Job = job, base: int = base) -> None:
                say(f"{job.target} ({job.env}): {message}", base + percent * 90 // len(jobs) // 100)

            if job.can_id is None:
                await bus.aflash_board(image, step)
            else:
                await bus.aflash_node(job.can_id, image, step)
        say("waiting for the flashed boards to come back", 90)
        return await _verify(bus, state, firmware, jobs, verify_timeout)
    finally:
        state.flashing = None


async def scan(
    bus: "UC2BusManager", state: "UC2State", timeout: float = 3.0
) -> tuple[Optional[UC2Node], list[UC2Node]]:
    """The board on the port and the CAN nodes, as they report themselves, into `state`."""
    board = await bus.aidentify()
    nodes = await bus.ascan_nodes(timeout)
    state.board = board
    state.nodes = nodes
    return board, nodes


async def _verify(
    bus: "UC2BusManager", state: "UC2State", firmware: Firmware, jobs: list[Job], timeout: float
) -> list[UC2Node]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    pending = list(jobs)
    nodes: list[UC2Node] = []
    while True:
        try:
            board, nodes = await scan(bus, state)
        except Exception as exc:  # the board is still rebooting  # noqa: BLE001
            logger.debug("rescan failed: %s", exc)
            board, nodes = None, []
        found = {node.can_id: node for node in nodes}
        pending = [
            job
            for job in pending
            if not (
                (reported := board if job.can_id is None else found.get(job.can_id)) is not None
                and runs(reported, job.pin, firmware)
            )
        ]
        if not pending:
            return nodes
        if loop.time() > deadline:
            missing = ", ".join(f"{job.target} ({job.env})" for job in pending)
            raise RuntimeError(
                f"flashed, but not running the new image after {timeout:.0f} s: {missing}"
            )
        await asyncio.sleep(2.0)
