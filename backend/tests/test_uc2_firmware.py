"""What is on a UC2 bus, and flashing the firmware the description names (no hardware)."""

import asyncio
import struct
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter

from newswitch.drivers.uc2 import firmware as fw
from newswitch.drivers.uc2.rest_bus import UC2RestBus
from newswitch.instrument import spec
from newswitch.instrument.hardware import Board, Firmware, FirmwarePin
from newswitch.models.uc2 import UC2Node
from newswitch.simulation.uc2_bus import VirtualUC2Bus
from newswitch.states.uc2 import UC2State

FAKE = Path(__file__).parent.parent / "instruments" / "fake-microscope"
RELEASE = "v2026.0.0-beta.4"
FIRMWARE = Firmware(
    release=RELEASE,
    board="UC2_canopen_master_release",
    nodes={11: "UC2_canopen_slave_motor_release_motX", 20: "UC2_canopen_slave_led_release"},
)


def esp_image(chip_id: int = 0, at: int = 0, size: int = 64) -> bytes:
    """An ESP image header (magic 0xE9, the chip id at 12) at `at`, padded with 0xFF."""
    header = bytearray(16)
    header[0] = fw.ESP_IMAGE_MAGIC
    struct.pack_into("<H", header, 12, chip_id)
    return b"\xff" * at + bytes(header) + b"\xff" * size


# --- the description ---------------------------------------------------------------------------


def test_the_description_names_the_firmware_apart_from_the_link() -> None:
    """``firmware`` is the board's own, never an option of its bus."""
    board = spec.load(FAKE).hardware.board
    assert board is not None and board.firmware is not None
    assert board.firmware.release.startswith("v")
    assert board.firmware.nodes[10].env.startswith("UC2_canopen_slave_motor")
    assert "firmware" not in board.options


@pytest.mark.parametrize(
    "firmware, finding",
    [
        ({"release": "v1", "image": "x"}, "image"),
        ({"board": "UC2_canopen_master_release"}, "release"),
        ({"release": "v1", "nodes": {"eleven": "x"}}, "nodes"),
    ],
)
def test_a_firmware_that_does_not_validate_is_refused(
    firmware: dict[str, Any], finding: str
) -> None:
    """Unknown keys, no release, a node id that is no number."""
    with pytest.raises(Exception, match=finding):
        TypeAdapter(Board).validate_python(
            {"name": "uc2", "transport": "rest", "firmware": firmware}
        )


# --- what a board reports ----------------------------------------------------------------------

SCAN_REPLY = {
    "master": {"canId": 1, "fwVersion": RELEASE, "mac": "AA:BB:CC:DD:EE:01"},
    "scan": [
        {
            "canId": 11,
            "deviceTypeStr": "motor",
            "statusStr": "idle",
            "fwVersion": RELEASE,
            "fwImage": "esp32_UC2_canopen_slave_motor_release_motX.bin",
            "build": "Nov 20 2026 10:00:00",
            "mac": "AA:BB:CC:DD:EE:11",
        },
        {"canId": 20, "deviceTypeStr": "led", "statusStr": "unreachable"},
    ],
    "count": 2,
    "qid": 1,
}


@pytest.mark.parametrize("reply", [SCAN_REPLY, [SCAN_REPLY], [{"qid": 0}, SCAN_REPLY]])
def test_a_scan_reply_lists_each_node_as_it_says(reply: Any) -> None:  # noqa: ANN401
    """A dict, or a list of replies holding one."""
    master, entries = fw.scan_entries(reply)
    assert master is not None and master["canId"] == 1
    nodes = [fw.node_from_scan(entry) for entry in entries]
    assert [(n.can_id, n.kind, n.status) for n in nodes] == [
        (11, "motor", "idle"),
        (20, "led", "unreachable"),
    ]
    assert nodes[0].image == "esp32_UC2_canopen_slave_motor_release_motX.bin"
    assert nodes[0].mac == "AA:BB:CC:DD:EE:11"


@pytest.mark.parametrize("reply", [None, {}, [], {"qid": 1}, "garbage"])
def test_an_empty_scan_reply_is_no_nodes(reply: Any) -> None:  # noqa: ANN401
    """Nothing to list, nothing listed."""
    assert fw.scan_entries(reply) == (None, [])


def test_the_board_identifies_itself_by_its_state() -> None:
    """``/state_get``: its image, version and build, and what it is, from the image."""
    reply = {
        "state": {
            "identifier_name": "UC2_Feather",
            "identifier_version": RELEASE,
            "identifier_image": "esp32_UC2_canopen_master_release.bin",
            "identifier_date": "Nov 20 2026",
            "pindef": "UC2_canopen_master",
        },
        "qid": 1,
    }
    board = fw.board_from_state([reply], wanted="UC2_canopen_master_release")
    assert board is not None
    assert (board.kind, board.firmware, board.wanted) == (
        "master",
        RELEASE,
        "UC2_canopen_master_release",
    )
    assert fw.runs(board, FirmwarePin(env="UC2_canopen_master_release"), FIRMWARE)
    assert fw.board_from_state({"state": {"pindef": "x"}}) is None


def test_a_node_runs_an_env_by_its_image_and_release() -> None:
    """Another image, or the same image of another release, is not what is wanted."""
    node = UC2Node(
        can_id=11, image="esp32_UC2_canopen_slave_motor_release_motX.bin", firmware=RELEASE
    )
    motx, moty = (
        FirmwarePin(env="UC2_canopen_slave_motor_release_motX"),
        FirmwarePin(env="UC2_canopen_slave_motor_release_motY"),
    )
    assert fw.runs(node, motx, FIRMWARE)
    assert not fw.runs(node, moty, FIRMWARE)
    assert not fw.runs(node, motx, Firmware(release="v2027.0.0"))
    build = UC2Node(can_id=11, image=node.image, firmware=f"{RELEASE}-13-ge86ebf3-t20261102085646")
    assert not fw.runs(build, motx, FIRMWARE)  # a build after the release is not the release
    pinned = FirmwarePin(env=motx.env, version=build.firmware)
    assert fw.runs(build, pinned, FIRMWARE)  # unless it is pinned


# --- what is to be flashed ---------------------------------------------------------------------


def node(can_id: int, image: str, version: str = "old") -> UC2Node:
    """A node running `image` of `version`."""
    return UC2Node(can_id=can_id, image=image, firmware=version)


def test_the_board_is_flashed_first_and_what_runs_it_is_left_alone() -> None:
    """The documented order: the board over USB, then the nodes."""
    board = node(1, "esp32_UC2_canopen_master_release.bin")
    nodes = [
        node(11, "esp32_UC2_canopen_slave_motor_release_motX.bin", RELEASE),
        node(20, "esp32_UC2_canopen_slave_laser_release.bin"),
    ]
    jobs = fw.plan(FIRMWARE, board, nodes)
    assert [(job.can_id, job.env) for job in jobs] == [
        (None, "UC2_canopen_master_release"),
        (20, "UC2_canopen_slave_led_release"),
    ]
    assert "laser" in jobs[1].why
    forced = fw.plan(FIRMWARE, board, nodes, with_board=False, force=True)
    assert [job.can_id for job in forced] == [11, 20]


def test_a_node_asked_for_must_have_an_env_and_be_on_the_bus() -> None:
    """Otherwise there is nothing to flash it with, or nothing to flash."""
    nodes = [node(11, "x")]
    with pytest.raises(ValueError, match="no firmware for node 12"):
        fw.plan(FIRMWARE, None, nodes, only=[12], with_board=False)
    with pytest.raises(ValueError, match="node 20 is not on the bus"):
        fw.plan(FIRMWARE, None, nodes, only=[20], with_board=False)
    assert [job.can_id for job in fw.plan(FIRMWARE, None, nodes, with_board=False)] == [11]


# --- fetching ----------------------------------------------------------------------------------


def test_a_release_publishes_each_env_twice() -> None:
    """The app alone, and merged with bootloader and partitions."""
    assert fw.image_url(FIRMWARE, FirmwarePin(env="UC2_canopen_master_release")) == (
        f"https://github.com/youseetoo/uc2-esp32/releases/download/{RELEASE}/"
        "esp32_UC2_canopen_master_release.bin"
    )
    assert fw.image_url(FIRMWARE, FirmwarePin(env="x"), full=True).endswith(
        f"/{RELEASE}/esp32_x_merged.bin"
    )
    other = FirmwarePin(env="x", release="v2025.1")
    assert fw.image_url(FIRMWARE, other).endswith("/v2025.1/esp32_x.bin")


def test_the_chip_is_read_off_the_image() -> None:
    """At 0, or at 0x1000 for an ESP32's merged image; no magic is no image."""
    assert fw.chip_of(esp_image(0)) == "esp32"
    assert fw.chip_of(esp_image(9)) == "esp32s3"
    assert fw.chip_of(esp_image(0, at=0x1000)) == "esp32"
    with pytest.raises(ValueError, match="not an ESP image"):
        fw.chip_of(b"<html>not found</html>" * 10)


def test_an_image_is_downloaded_once_and_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Into the cache, by release; the merged one is written at 0, the app at 0x10000."""
    downloads: list[str] = []

    def download(url: str, target: Path) -> None:
        downloads.append(url)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(esp_image(9))

    monkeypatch.setattr(fw, "_download", download)
    app = asyncio.run(
        fw.fetch(FIRMWARE, FirmwarePin(env="UC2_canopen_slave_led_release"), cache=tmp_path)
    )
    again = asyncio.run(
        fw.fetch(FIRMWARE, FirmwarePin(env="UC2_canopen_slave_led_release"), cache=tmp_path)
    )
    merged = asyncio.run(
        fw.fetch(
            FIRMWARE, FirmwarePin(env="UC2_canopen_slave_led_release"), full=True, cache=tmp_path
        )
    )
    assert len(downloads) == 2 and app.path == again.path
    assert app.path == tmp_path / RELEASE / "esp32_UC2_canopen_slave_led_release.bin"
    assert (app.chip, app.offset, merged.offset) == ("esp32s3", fw.APP_OFFSET, 0)


def test_what_is_no_image_is_not_kept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A release's 404 page, say, is refused and removed."""

    def download(url: str, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"Not Found" * 20)

    monkeypatch.setattr(fw, "_download", download)
    with pytest.raises(ValueError, match="not an ESP image"):
        asyncio.run(fw.fetch(FIRMWARE, FirmwarePin(env="x"), cache=tmp_path))
    assert not (tmp_path / RELEASE / "esp32_x.bin").exists()


# --- flashing over USB -------------------------------------------------------------------------


def fake_esptool(tmp_path: Path, exit_code: int) -> Path:
    """A python that, run as ``-m esptool ...``, records its arguments and prints esptool's
    progress."""
    script = tmp_path / "python"
    script.write_text(
        "#!/bin/sh\n"
        f'echo "$@" > {tmp_path / "args"}\n'
        'echo "Writing at 0x00010000 [====] 50.0% 1/2 bytes... (50 %)"\n'
        'echo "Writing at 0x00020000 [====] 100.0% 2/2 bytes... (100 %)"\n'
        f"exit {exit_code}\n"
    )
    script.chmod(0o755)
    return script


def test_the_board_is_written_with_esptool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The app at 0x10000, keeping the flash's settings; progress as esptool reports it."""
    monkeypatch.setattr(sys, "executable", str(fake_esptool(tmp_path, 0)))
    image = fw.FirmwareImage(path=tmp_path / "app.bin", chip="esp32", offset=fw.APP_OFFSET, url="")
    seen: list[int] = []
    asyncio.run(
        fw.esptool_flash("/dev/ttyUSB9", image, lambda message, percent: seen.append(percent))
    )
    args = (tmp_path / "args").read_text().split()
    assert args[:2] == ["-m", "esptool"]
    assert ["--chip", "esp32", "--port", "/dev/ttyUSB9"] == args[2:6]
    assert args[-2:] == ["0x10000", str(tmp_path / "app.bin")]
    assert "keep" in args and seen and seen[-1] == 100


def test_a_failing_esptool_says_why(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Its output comes along; the merged image goes to 0 without keep."""
    monkeypatch.setattr(sys, "executable", str(fake_esptool(tmp_path, 2)))
    image = fw.FirmwareImage(path=tmp_path / "all.bin", chip="esp32", offset=0, url="")
    with pytest.raises(RuntimeError, match="esptool failed"):
        asyncio.run(fw.esptool_flash("/dev/ttyUSB9", image))
    args = (tmp_path / "args").read_text().split()
    assert "keep" not in args and args[-2] == "0x0"


# --- bringing a bus to what its description wants ----------------------------------------------


async def fake_fetch(firmware: Firmware, pin: FirmwarePin, full: bool) -> fw.FirmwareImage:
    """An image of `pin`, as if downloaded: the build it pins."""
    name = f"esp32_{pin.env}{'_merged' if full else ''}.bin"
    return fw.FirmwareImage(
        path=Path("/cache") / name,
        chip="esp32",
        offset=0 if full else 0x10000,
        url=name,
        version=firmware.version_of(pin),
    )


def test_update_flashes_the_board_then_the_nodes_and_checks_them() -> None:
    """Each flashed board reports the wanted image of the release afterwards; nothing else is
    touched, and what is flashing is said in the state while it lasts."""
    state = UC2State()
    bus = VirtualUC2Bus(state, firmware=FIRMWARE)
    said: list[str] = []
    nodes = asyncio.run(
        fw.update(
            bus, state, fetcher=fake_fetch, report=lambda m, p: said.append(m), verify_timeout=1
        )
    )
    assert bus.flashed == [None, 11, 20]
    running = {n.can_id: n for n in nodes}
    assert fw.runs(running[11], FIRMWARE.nodes[11], FIRMWARE)
    assert fw.runs(running[20], FIRMWARE.nodes[20], FIRMWARE)
    assert running[12].firmware == "virtual"  # no env named: left alone
    assert state.board is not None and fw.runs(state.board, FIRMWARE.board, FIRMWARE)  # type: ignore[arg-type]
    assert state.flashing is None and any("node 20" in message for message in said)
    # Run again: everything runs what is wanted.
    asyncio.run(fw.update(bus, state, fetcher=fake_fetch, verify_timeout=1))
    assert bus.flashed == [None, 11, 20]


def test_a_full_flash_writes_the_merged_image_to_the_board_alone() -> None:
    """A node takes the app alone, whatever is asked."""
    state = UC2State()
    bus = VirtualUC2Bus(state, firmware=FIRMWARE)
    asked: list[tuple[str, bool]] = []

    async def fetch(firmware: Firmware, pin: FirmwarePin, full: bool) -> fw.FirmwareImage:
        asked.append((pin.env, full))
        return await fake_fetch(firmware, pin, full)

    asyncio.run(fw.update(bus, state, only=[11], full=True, fetcher=fetch, verify_timeout=1))
    assert asked == [
        ("UC2_canopen_master_release", True),
        ("UC2_canopen_slave_motor_release_motX", False),
    ]


def test_a_board_that_does_not_come_back_running_it_fails() -> None:
    """Flashed, but still reporting the old image: an error naming it."""
    state = UC2State()
    bus = VirtualUC2Bus(state, firmware=FIRMWARE)

    async def nothing_changes(can_id: int, image: fw.FirmwareImage, report: fw.Report) -> None:
        pass

    bus.aflash_node = nothing_changes  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="node 11"):
        asyncio.run(
            fw.update(bus, state, only=[11], with_board=False, fetcher=fake_fetch, verify_timeout=0)
        )
    assert state.flashing is None


def test_without_a_named_firmware_nothing_is_flashed() -> None:
    """The description has to say what to flash."""
    state = UC2State()
    with pytest.raises(ValueError, match="names no firmware"):
        asyncio.run(fw.update(VirtualUC2Bus(state), state, fetcher=fake_fetch))


# --- the serial transport ----------------------------------------------------------------------


class FakeRestClient:
    """What `UC2RestBus` asks of UC2-REST's client: a scan and the state."""

    def __init__(self, scan: Any, state: Any) -> None:  # noqa: ANN401
        outer = self

        class Can:
            def scan(self, timeout: float = 5) -> Any:  # noqa: ANN401
                return outer._scan

        class State:
            def get_state(self, timeout: float = 3) -> Any:  # noqa: ANN401
                return outer._state

        self._scan, self._state = scan, state
        self.sync = type("Sync", (), {"can": Can(), "state": State()})()

    async def call(self, fn: Any) -> Any:  # noqa: ANN401
        return fn()


def test_the_serial_bus_scans_through_the_master() -> None:
    """The master's scan and state, as nodes; the wanted env from the description."""
    bus = UC2RestBus(UC2State(), firmware=FIRMWARE)
    bus._client = FakeRestClient(
        [SCAN_REPLY], {"state": {"identifier_image": "esp32_UC2_canopen_master_release.bin"}}
    )  # type: ignore[assignment]
    bus._connected.set()
    nodes = asyncio.run(bus.ascan_nodes())
    assert [(n.can_id, n.wanted) for n in nodes] == [
        (11, FIRMWARE.nodes[11].env),
        (20, FIRMWARE.nodes[20].env),
    ]
    assert bus.state.nodes_online == [11, 20]
    board = asyncio.run(bus.aidentify())
    assert board is not None and board.kind == "master" and board.wanted == FIRMWARE.board.env  # type: ignore[union-attr]


# --- the CANopen transport, on a virtual CAN bus -----------------------------------------------


def test_a_node_is_identified_and_updated_over_sdo() -> None:
    """Segmented reads of its identity strings; the OTA writes CRC, then size, then the image."""
    can = pytest.importorskip("can")
    canopen = pytest.importorskip("canopen")
    from newswitch.drivers.uc2 import canopen_sdo

    channel = f"ota-{time.monotonic_ns()}"
    server_bus = can.Bus(interface="virtual", channel=channel, receive_own_messages=False)
    client_bus = can.Bus(interface="virtual", channel=channel, receive_own_messages=False)
    od = canopen.ObjectDictionary()
    entries = {
        canopen_sdo.FIRMWARE_VERSION: (canopen.objectdictionary.VISIBLE_STRING, RELEASE.encode()),
        canopen_sdo.BOARD_IMAGE: (
            canopen.objectdictionary.VISIBLE_STRING,
            b"esp32_UC2_canopen_slave_led_release.bin",
        ),
        canopen_sdo.BUILD_TIMESTAMP: (
            canopen.objectdictionary.VISIBLE_STRING,
            b"Nov 20 2026 10:00:00",
        ),
        canopen_sdo.MAC_ADDRESS: (canopen.objectdictionary.VISIBLE_STRING, b"AA:BB:CC:DD:EE:14"),
        canopen_sdo.OTA_DATA: (canopen.objectdictionary.DOMAIN, b""),
        canopen_sdo.OTA_SIZE: (canopen.objectdictionary.UNSIGNED32, 0),
        canopen_sdo.OTA_CRC32: (canopen.objectdictionary.UNSIGNED32, 0),
        canopen_sdo.OTA_STATUS: (canopen.objectdictionary.UNSIGNED8, canopen_sdo.OTA_COMPLETE),
        canopen_sdo.OTA_ERROR: (canopen.objectdictionary.UNSIGNED8, 0),
    }
    for index, (kind, default) in entries.items():
        variable = canopen.objectdictionary.ODVariable(f"x{index:04X}", index, 0)
        variable.data_type = kind
        variable.access_type = "rw"
        variable.default = default
        od.add_object(variable)
    server = canopen.Network(server_bus)
    server.connect()
    local = server.create_node(20, od)
    writes: list[int] = []
    received = bytearray()

    def written(index: int, subindex: int, od: Any, data: bytes) -> None:  # noqa: ANN401
        writes.append(index)
        if index == canopen_sdo.OTA_DATA:
            received.extend(data)

    local.add_write_callback(written)
    notifier = can.Notifier(client_bus, [])
    try:
        attached = canopen_sdo.Attached(client_bus, notifier, response_timeout=2.0)
        identity = canopen_sdo.read_identity(attached, 20)
        assert identity["fwVersion"] == RELEASE
        assert identity["fwImage"] == "esp32_UC2_canopen_slave_led_release.bin"
        assert identity["mac"] == "AA:BB:CC:DD:EE:14"
        image = esp_image(9, size=10_000)
        percents: list[int] = []
        canopen_sdo.flash_node(attached, 20, image, percents.append)
        attached.detach()
    finally:
        notifier.stop()
        server.disconnect()
        client_bus.shutdown()
    assert writes[:2] == [canopen_sdo.OTA_CRC32, canopen_sdo.OTA_SIZE]
    assert canopen_sdo.OTA_DATA in writes and bytes(received) == image
    assert percents[-1] == 100


# --- pinned builds -----------------------------------------------------------------------------

BUILD = f"{RELEASE}-13-ge86ebf3-t20261102085646"


def test_an_env_alone_or_a_pinned_build() -> None:
    """A node is an env (of the release), or a pin: an env, the version it reports, its release."""
    firmware = TypeAdapter(Firmware).validate_python(
        {
            "release": RELEASE,
            "board": "UC2_canopen_master_release",
            "nodes": {11: "motX", 12: {"env": "motY", "version": BUILD, "release": "v1"}},
        }
    )
    assert firmware.board == FirmwarePin(env="UC2_canopen_master_release")
    assert firmware.version_of(firmware.nodes[11]) == RELEASE
    assert (firmware.version_of(firmware.nodes[12]), firmware.release_of(firmware.nodes[12])) == (
        BUILD,
        "v1",
    )
    assert firmware.on_start == "flash"
    assert firmware.pin_for(None) == firmware.board and firmware.pin_for(99) is None


def test_an_image_says_its_version_in_its_app_descriptor() -> None:
    """``esp_app_desc_t`` after the image header; in a merged image, after the app's at 0x10000."""
    descriptor = (
        struct.pack("<I", fw.APP_DESC_MAGIC) + b"\0" * 12 + RELEASE.encode().ljust(32, b"\0")
    )
    app = esp_image(9, size=0) + b"\xff" * 0x10 + descriptor + b"\0" * 64
    assert fw.app_version(app) == RELEASE
    assert fw.app_version(b"\xff" * fw.APP_OFFSET + app, full=True) == RELEASE
    assert fw.app_version(esp_image(9)) == ""


def test_a_pinned_build_is_flashed_only_from_that_build() -> None:
    """A node pinned to a development build, and an image of the release: refused, nothing written."""
    pinned = Firmware(
        release=RELEASE,
        nodes={11: FirmwarePin(env="UC2_canopen_slave_motor_release_motX", version=BUILD)},
    )
    state = UC2State()
    bus = VirtualUC2Bus(state, firmware=pinned)

    async def release_image(firmware: Firmware, pin: FirmwarePin, full: bool) -> fw.FirmwareImage:
        image = await fake_fetch(firmware, pin, full)
        return fw.FirmwareImage(
            path=image.path, chip=image.chip, offset=image.offset, url=image.url, version=RELEASE
        )

    with pytest.raises(ValueError, match=f"pinned to .* {BUILD}, but .* is {RELEASE}"):
        asyncio.run(fw.update(bus, state, fetcher=release_image, verify_timeout=0))
    assert bus.flashed == [] and state.flashing is None


class OnRealHardware:
    """A simulated bus that is not the virtual one: as a real transport looks to `keep_firmware`."""

    keeps_firmware = True

    def __init__(self, bus: VirtualUC2Bus) -> None:
        self._bus = bus

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401
        return getattr(self._bus, name)


@pytest.mark.parametrize("on_start", ["flash", "check", "off"])
def test_on_start_the_bus_is_brought_to_the_description(
    on_start: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``flash`` flashes what differs, ``check`` says so in the state, ``off`` leaves it alone."""
    from dataclasses import replace

    from newswitch.actions.uc2 import keep_firmware
    from newswitch.drivers.uc2.boards import UC2Boards

    monkeypatch.setattr(fw, "fetch", fake_fetch)
    state = UC2State()
    virtual = VirtualUC2Bus(state, firmware=replace(FIRMWARE, on_start=on_start))
    asyncio.run(keep_firmware(UC2Boards({"uc2": OnRealHardware(virtual)}, state), state))  # type: ignore[arg-type]
    if on_start == "flash":
        assert virtual.flashed == [None, 11, 20] and state.last_error == ""
    elif on_start == "check":
        assert virtual.flashed == [] and "node 11" in state.last_error
    else:
        assert virtual.flashed == [] and state.last_error == ""


def test_the_virtual_bus_is_not_flashed_on_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulated, nothing is real to flash."""
    from newswitch.actions.uc2 import keep_firmware
    from newswitch.drivers.uc2.boards import UC2Boards

    monkeypatch.setattr(fw, "fetch", fake_fetch)
    state = UC2State()
    bus = VirtualUC2Bus(state, firmware=FIRMWARE)
    asyncio.run(keep_firmware(UC2Boards({"uc2": bus}, state), state))
    assert bus.flashed == []


def test_a_failure_on_start_is_said_and_the_server_runs_on() -> None:
    """A bus that cannot be reached: the state says why; nothing raises."""
    from newswitch.actions.uc2 import keep_firmware
    from newswitch.drivers.uc2.boards import UC2Boards

    state = UC2State()
    virtual = VirtualUC2Bus(state, firmware=FIRMWARE)

    async def unreachable() -> None:
        raise RuntimeError("no UC2 board answered")

    virtual.aidentify = unreachable  # type: ignore[method-assign]
    asyncio.run(keep_firmware(UC2Boards({"uc2": OnRealHardware(virtual)}, state), state))  # type: ignore[arg-type]
    assert "no UC2 board answered" in state.last_error


def test_johannes_frame_pins_what_its_bus_runs() -> None:
    """The frame's description: its board on the CP2102, and each node pinned to its build."""
    instrument = spec.load(Path(__file__).parent.parent / "instruments" / "johannes-frame")
    board = instrument.hardware.board
    assert board is not None and board.transport == "canopen" and board.firmware is not None
    firmware = board.firmware
    assert firmware.on_start == "flash" and sorted(firmware.nodes) == [10, 11, 12, 13, 20, 30]
    motx = UC2Node(
        can_id=11,
        image="esp32_UC2_canopen_slave_motor_release_motX.bin",
        firmware="v2026.0.0-beta.4-9-g3c86acd-t20260930173005-pr133",
    )
    assert fw.runs(motx, firmware.nodes[11], firmware)


# --- a stage that must not move ----------------------------------------------------------------


@pytest.mark.parametrize("transport", ["rest", "canopen"])
def test_a_board_without_motion_refuses_every_motion_before_sending(transport: str) -> None:
    """Moves, homing and the objective changer are refused with no connection asked for: nothing
    can reach the board (there is none here, and the refusal comes first)."""
    from newswitch.drivers.uc2.canopen_bus import UC2CanBus, UC2CanBusConfig
    from newswitch.drivers.uc2.rest_bus import UC2RestBusConfig

    bus = (
        UC2RestBus(UC2State(), UC2RestBusConfig(allow_motion=False))
        if transport == "rest"
        else UC2CanBus(UC2State(), UC2CanBusConfig(allow_motion=False))
    )
    for call in (
        bus.amove_axis("X", 100.0),
        bus.ahome_axis("Z"),
        bus.aobjective_move(2),
        bus.aobjective_home(),
    ):
        with pytest.raises(PermissionError, match="motion is disabled"):
            asyncio.run(call)


def test_johannes_frame_moves_its_stage_on_its_board() -> None:
    """Its stage's X, Y and Z are the board's steppers, and its board lets them move."""
    instrument = spec.load(Path(__file__).parent.parent / "instruments" / "johannes-frame")
    moves = {v.name: v for v in instrument.variables.values() if v.verb == "moves"}
    assert {n: v.actuator for n, v in moves.items()} == {
        "stage.x": "stg-x",
        "stage.y": "stg-y",
        "stage.z": "stg-z",
    }
    axes = {
        a.name: a.options["axis"]
        for a in instrument.hardware.actuators.values()
        if a.driver == "uc2.stepper"
    }
    assert axes == {"stg-x": "X", "stg-y": "Y", "stg-z": "Z"}
    board = instrument.hardware.board
    assert board is not None and board.options.get("allow_motion", True) is True


def test_johannes_frame_talks_canopen_on_can0_with_its_node_ids(tmp_path: Path) -> None:
    """Its bus is the Pi's can0, with this frame's node map, not uc2canopen's defaults."""
    from newswitch.drivers.uc2.canopen_bus import UC2CanBus
    from newswitch.microscope.parts import build_uc2_bus
    from tests.conftest import run_settings

    instrument = spec.load(Path(__file__).parent.parent / "instruments" / "johannes-frame")
    bus = build_uc2_bus(run_settings(tmp_path, simulate="unwired"), instrument, UC2State())
    assert isinstance(bus, UC2CanBus) and not bus.has_port_board
    config = bus.config
    assert (config.interface, config.channel, config.bitrate) == ("socketcan", "can0", 500000)
    nodes = (
        config.node_a,
        config.node_x,
        config.node_y,
        config.node_z,
        config.node_laser,
        config.node_led,
    )
    assert nodes == (10, 11, 12, 13, 20, 30)
    assert bus.firmware is not None and sorted(bus.firmware.nodes) == [10, 11, 12, 13, 20, 30]


def test_on_canopen_only_the_can_nodes_are_flashed() -> None:
    """No board is on a port: its pin is skipped, the nodes are checked and flashed."""
    state = UC2State()
    virtual = VirtualUC2Bus(state, firmware=FIRMWARE)
    virtual.has_port_board = False  # type: ignore[misc]
    asyncio.run(fw.update(virtual, state, fetcher=fake_fetch, verify_timeout=1))
    assert virtual.flashed == [11, 20]


def test_a_laser_on_its_own_node_is_set_there() -> None:
    """A laser channel with a node goes to that node; without one, the bus's laser node."""
    import koil

    from newswitch.drivers.uc2.actuators import Laser, LaserConfig

    calls: list[tuple] = []

    class Bus:
        async def aset_laser(self, channel: int, value: int, node: int | None = None) -> None:
            calls.append((channel, value, node))

    with koil.Koil():
        Laser(Bus(), LaserConfig(channel=0, node=30), maximum=10.0).set(5.0, lambda v: None)  # type: ignore[arg-type]
        Laser(Bus(), LaserConfig(channel=2), maximum=10.0).set(10.0, lambda v: None)  # type: ignore[arg-type]
    assert calls == [(0, 512, 30), (2, 1023, None)]


# --- where an axis's 0 is, and how it homes ---------------------------------------------------


def test_an_axis_homes_as_it_says_over_the_defaults() -> None:
    """Its own direction, speed, timeout, back-off and polarity; the rest the bus's home_*. The
    polarity and back-off are written to its node before homing starts."""
    from newswitch.drivers.uc2.canopen_bus import UC2CanBus, UC2CanBusConfig

    config = UC2CanBusConfig(
        node_z=13,
        homing={"Z": {"direction": 1, "speed": 10000, "release": -10000, "polarity": 1}},
    )
    bus = UC2CanBus(UC2State(), config)
    assert bus.homing_for_axis("X") == {"direction": -1, "speed": 15000, "timeout_ms": 20000}
    calls: list[tuple] = []

    class Sdo:
        def write_u8(self, *args: int) -> None:
            calls.append(("u8", *args))

        def write_i32(self, *args: int) -> None:
            calls.append(("i32", *args))

    class Motor:
        seen = True

        def __init__(self) -> None:
            # "done" of the last homing first, then this one's "homing", then its "done"
            self.statuses = [2, 2, 1, 1, 2]

        @property
        def homing_status(self) -> int:
            return self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]

    motor = Motor()

    class Listener:
        def get_motor(self, node: int, sub: int) -> Motor:
            calls.append(("read", node, sub))
            return motor

    class Client:
        sync = type("Sync", (), {"_sdo": Sdo(), "_listener": Listener()})()

        async def home(self, **kwargs: int) -> None:
            calls.append(("home", kwargs))

    bus._client = Client()  # type: ignore[assignment]
    bus._connected.set()
    asyncio.run(bus.ahome_axis("Z"))
    assert calls[:2] == [("u8", 13, 0x2015, 1, 1), ("i32", 13, 0x2014, 1, -10000)]
    home = calls[2][1]
    assert (home["direction"], home["speed"], home["timeout_ms"], home["node_id"]) == (1, 10000, 20000, 13)
    # it waited through the stale "done" for this homing's own end
    assert motor.statuses == [2] and len([c for c in calls if c[0] == "read"]) == 5

    with pytest.raises(ValueError, match="unknown"):
        UC2CanBus(UC2State(), UC2CanBusConfig(homing={"X": {"dir": 1}})).homing_for_axis("X")


def test_a_move_that_never_says_it_runs_is_over_soon() -> None:
    """A move to where the axis is, or a very short one, never broadcasts running: it is over
    after MOVE_START_S, not after the move timeout; a long one once it stops."""
    import time

    from newswitch.drivers.uc2 import canopen_bus
    from newswitch.drivers.uc2.canopen_bus import UC2CanBus, UC2CanBusConfig

    class Motor:
        seen = True
        position = 0

        def __init__(self, runs_for: float) -> None:
            self.until = time.monotonic() + runs_for

        @property
        def running(self) -> bool:
            return time.monotonic() < self.until

    class Client:
        def __init__(self, runs_for: float) -> None:
            motor = Motor(runs_for)
            listener = type("Listener", (), {"get_motor": lambda self, n, s: motor})()
            self.sync = type("Sync", (), {"_listener": listener})()

        async def move(self, **kwargs: int) -> None:
            pass

    bus = UC2CanBus(UC2State(), UC2CanBusConfig(steps_per_um_x=-3.2, move_timeout_s=5.0))
    for runs_for, at_least, at_most in ((0.0, 0.5, 1.5), (1.2, 1.1, 1.6)):
        bus._client = Client(runs_for)  # type: ignore[assignment]
        bus._connected.set()
        started = time.monotonic()
        where = asyncio.run(bus.amove_axis("X", 1000.0, is_absolute=True))
        took = time.monotonic() - started
        assert at_least <= took <= at_most and where == pytest.approx(1000.0, abs=0.5)
    assert canopen_bus.MOVE_START_S < 1.0


def test_a_zero_from_an_axis_at_rest_known_elsewhere_is_not_believed() -> None:
    """The motor firmware alternates its position broadcast with one saying 0, at rest too: that 0
    is dropped while the axis is known elsewhere; a real 0 (after homing, or reached moving) is
    not."""
    from newswitch.drivers.uc2.canopen_bus import UC2CanBus, UC2CanBusConfig

    bus = UC2CanBus(UC2State(), UC2CanBusConfig())
    seen = [bus._believed("X", steps, running=False) for steps in (-58692, 0, -58692, 0)]
    assert seen == [True, False, True, False]
    assert bus._believed("X", 0, running=True)  # passing through 0 while moving
    assert bus._believed("X", 0, running=False)  # and standing there now
    assert bus._believed("Y", 0, running=False)  # nothing known yet: believed


def test_a_moving_axis_is_passed_on_ten_times_a_second_and_where_it_stops_always() -> None:
    """A node broadcasts every 10 ms while running: a tenth of that is passed on; the report of it
    standing still is passed on at once."""
    from newswitch.drivers.uc2.canopen_bus import UC2CanBus, UC2CanBusConfig

    bus = UC2CanBus(UC2State(), UC2CanBusConfig(position_update_min_interval_s=0.1))

    async def reports() -> list[bool]:
        passed = []
        for _ in range(50):  # half a second of a move, every 10 ms
            passed.append(bus._due("X", running=True))
            await asyncio.sleep(0.01)
        passed.append(bus._due("X", running=False))  # it stopped
        return passed

    passed = asyncio.run(reports())
    assert 4 <= sum(passed[:-1]) <= 7 and passed[-1]
