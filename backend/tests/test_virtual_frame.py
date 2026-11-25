"""johannes-frame as its digital twin (``simulate: virtual``), and the debug simulation (``debug``)."""

import asyncio
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import koil
import numpy as np
import pytest

from newswitch.drivers.simulator import SimulatedMicroscope
from newswitch.drivers.uc2.actuators import Laser, LedArray, Stepper
from newswitch.drivers.uc2.dispatch import dispatch_uc2_events
from newswitch.drivers.uc2.virtual_bus import VirtualUC2Bus
from newswitch.instrument import spec
from newswitch.instrument.errors import SpecError
from newswitch.microscope.parts import build_microscope
from newswitch.routines.mount_calibration import bright_spot, calibrate_mount
from newswitch.settings import CONFIG_ENV_VAR, SIMULATE_ENV_VAR, load_settings
from newswitch.states.mount_calibration import MountCalibrationState
from tests.conftest import run_settings

FRAME = Path(__file__).parent.parent / "instruments" / "johannes-frame"


def pinhole_um(instrument: spec.Instrument) -> tuple[float, float]:
    """Where the description puts the calibration slide's middle pinhole on the stage."""
    holding = instrument.sample_holder("stage")
    mount = holding.holders["slides"].mount
    x, y = holding.mark_on_holder()
    return (x + mount.x) * 1000.0, (y + mount.y) * 1000.0


# --- the run switch ------------------------------------------------------------------------------


def test_the_switch_runs_a_description_otherwise_without_touching_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CONFIG_ENV_VAR, str(FRAME))
    assert load_settings().simulate == "unwired"  # as the file says
    rig = load_settings()
    monkeypatch.setenv(SIMULATE_ENV_VAR, "virtual")
    twin = load_settings()
    assert twin.simulate == "virtual"
    # beside the rig, with files of its own: the rig's cache is not cleared by the twin's start
    assert twin.db_path.endswith("arkitekt_agent.virtual.db") and twin.db_path != rig.db_path
    assert twin.cache_dir == rig.cache_dir / "virtual" and twin.image_dir == rig.image_dir / "virtual"
    monkeypatch.setenv(SIMULATE_ENV_VAR, "unwired")  # what the file says: nothing changes
    assert load_settings() == rig
    monkeypatch.setenv(SIMULATE_ENV_VAR, "sometimes")
    with pytest.raises(SpecError, match="no simulation mode"):
        load_settings()


# --- the twin ----------------------------------------------------------------------------------


def test_the_twin_runs_the_frames_drivers_on_a_board_like_its_own(tmp_path: Path) -> None:
    m = build_microscope(run_settings(tmp_path, simulate="virtual"), spec.load(FRAME))
    bus = m.uc2_bus
    assert isinstance(bus, VirtualUC2Bus) and not bus.has_port_board
    assert bus.config.node_kinds == {
        10: "motor", 11: "motor", 12: "motor", 13: "motor", 20: "laser", 30: "led", 40: "galvo"
    }
    assert m.values is not None
    kinds = {name: type(driver) for name, driver in m.values.drivers.items()}
    assert kinds["stage.x"] is Stepper and kinds["led.power"] is Laser
    assert kinds["ring.power"] is LedArray
    assert type(m.detector).__name__ == "SimulatedDetectorManager"
    assert bus.released("Z") == pytest.approx(-3125.0) and bus.released("X") == 0.0


def test_homing_the_twin_moves_the_stage_where_homing_leaves_it(tmp_path: Path) -> None:
    """Z backs off from its endstop as its homing says; the position reaches the stage's values
    through the bus's events, as on the real frame."""
    m = build_microscope(run_settings(tmp_path, simulate="virtual"), spec.load(FRAME))
    assert m.values is not None and m.uc2_bus is not None

    async def home() -> None:
        dispatch = asyncio.ensure_future(dispatch_uc2_events(m.uc2_bus, m.values, m.uc2_state))
        await asyncio.sleep(0)
        await m.uc2_bus.ahome_axis("Z")
        await asyncio.sleep(0.05)
        dispatch.cancel()

    asyncio.run(home())
    assert m.values["stage.z"] == pytest.approx(-3125.0)


def test_the_simulated_slide_is_black_but_for_its_pinholes() -> None:
    instrument = spec.load(FRAME)
    microscope = SimulatedMicroscope(instrument)
    x, y = pinhole_um(instrument)
    settings = {"stage.z": -3520.0, "led.power": 2e-3, "camera.exposure": 2.0}
    microscope.set({"stage.x": x, "stage.y": y, **settings})
    spot = bright_spot(microscope.image("camera"))
    assert spot is not None and abs(spot.x) < 1 and abs(spot.y) < 1 and not spot.cut
    microscope.set({"stage.x": x + 200.0, "stage.y": y, **settings})
    moved = bright_spot(microscope.image("camera"))
    assert moved is not None and abs(moved.x) > 100  # the image follows the stage
    microscope.set({"stage.x": x + 9000.0, "stage.y": y, **settings})  # between two pinholes
    assert bright_spot(microscope.image("camera")) is None


@pytest.mark.usefixtures("views_beside_copies")
def test_calibrating_the_twin_finds_where_its_holder_truly_is_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The truth puts the holder 150 / -80 µm off its description: the whole calibration (homing,
    the hold approved, search, centring) finds that, and the description stays as it was."""
    copy = tmp_path / "johannes-frame"
    shutil.copytree(FRAME, copy)
    (copy / "truth.yml").write_text("mount_offset_um: {x: 150.0, y: -80.0}\n")
    before = (copy / "microscope.yml").read_text()
    monkeypatch.setenv(CONFIG_ENV_VAR, str(copy))
    monkeypatch.setenv(SIMULATE_ENV_VAR, "virtual")
    instrument = spec.load(copy)
    m = build_microscope(run_settings(tmp_path, simulate="virtual"), instrument)
    described = instrument.sample_holder("stage").holders["slides"].mount
    holds: list[str] = []
    task = SimpleNamespace(
        progress=lambda *a, **k: None,
        hold=lambda message, prompt=None: holds.append(message) or SimpleNamespace(approved=True),
    )
    state = MountCalibrationState()

    async def run() -> Any:  # noqa: ANN401
        pump = asyncio.ensure_future(m.uc2_bus.abackground())
        dispatch = asyncio.ensure_future(dispatch_uc2_events(m.uc2_bus, m.values, m.uc2_state))
        try:
            return await koil.run_threaded(
                calibrate_mount, m.space, m.values, m.detector, m.uc2_bus, state, task
            )
        finally:
            pump.cancel()
            dispatch.cancel()

    result = asyncio.run(run())
    assert len(holds) == 1 and "Homed (Z, X, Y, A)" in holds[0]
    assert result.x_mm == pytest.approx(described.x + 0.150, abs=0.003)
    assert result.y_mm == pytest.approx(described.y - 0.080, abs=0.003)
    assert result.saved_to is None and state.last == result
    assert (copy / "microscope.yml").read_text() == before


# --- the debug simulation: the stream tested, not the camera ---------------------------------


def test_a_debug_stream_sends_the_time_it_sends_with_no_camera_behind_it() -> None:
    """Each stream sends test frames on its own, at the stream's pace: numbered one after another,
    the size the stream sends, drawn anew each time."""
    from newswitch.infra.streaming.lovekit import (
        TEST_PATTERN_SIZE,
        CameraStream,
        CameraStreams,
        LovekitSink,
        publish_camera_streams,
    )
    from tests.test_serving import FakeLovekit

    sink = LovekitSink([CameraStream("camera", "camera", "camera")], test_pattern=True)
    lovekit = FakeLovekit()

    async def run() -> None:
        task = asyncio.create_task(publish_camera_streams(lovekit, sink, CameraStreams()))  # type: ignore[arg-type]
        await asyncio.sleep(0.5)
        assert lovekit.published is not None
        lovekit.published.stopped.set()
        await asyncio.wait_for(task, timeout=2)

    asyncio.run(run())
    assert lovekit.published is not None
    frames = lovekit.published.tracks["camera"].frames
    width, height = TEST_PATTERN_SIZE
    assert 4 <= len(frames) <= 9  # 15 a second at most, without a camera offering any
    assert all(f.shape == (height, width, 4) and f.dtype == np.uint8 for f in frames)
    assert not np.array_equal(frames[0], frames[1]) and frames[0][..., :3].max() == 255


def test_the_agent_tests_the_network_under_debug(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from app import provide_lovekit_sink

    for mode, expected in (("debug", True), ("virtual", False)):
        run = SimpleNamespace(instrument=spec.load(FRAME), settings=run_settings(tmp_path, simulate=mode))
        sink, _ = asyncio.run(provide_lovekit_sink(run))  # type: ignore[arg-type]
        assert sink.test_pattern is expected


def test_a_light_that_is_off_is_acquired_at_its_preset_and_the_camera_is_not_saturated(
    tmp_path: Path,
) -> None:
    """johannes-frame's LED comes on at 2 µW (PWM 409) when an acquisition turns it on, not at
    its maximum, and its camera starts at 0.3 ms: off since the start, or switched off by the last
    acquisition, it is lit again at that."""
    from newswitch.instrument.errors import SpecError as Refused
    from newswitch.routines.mda import _power

    m = build_microscope(run_settings(tmp_path, simulate="virtual"), spec.load(FRAME))
    assert m.values is not None
    led = m.values.source_state.sources["led"]
    assert not led.on and led.lit_power == pytest.approx(2e-3) and _power(led) == pytest.approx(2e-3)
    assert m.values["camera.exposure"] == pytest.approx(0.3)
    with koil.Koil():  # the LED's own driver, on the twin's virtual board
        m.values.set({"led.power": 1e-3})
        m.values.set({"led.power": 0.0})  # off again, as an acquisition leaves it
    assert _power(m.values.source_state.sources["led"]) == pytest.approx(1e-3)  # the last it was on at

    copy = tmp_path / "frame"
    shutil.copytree(FRAME, copy)
    text = (copy / "microscope.yml").read_text()
    (copy / "microscope.yml").write_text(text.replace("lit: 2 uW", "lit: 9 uW"))
    with pytest.raises(Refused, match="lit"):
        spec.load(copy)


def test_two_lights_alike_are_two_channels_of_two_names(tmp_path: Path) -> None:
    """The frame's white LED and its white ring light the camera alike: named only by what their
    path does, they were one name, and picking it could take the ring (the LED then off)."""
    m = build_microscope(run_settings(tmp_path, simulate="virtual"), spec.load(FRAME))
    names = {channel.source: channel.name for channel in m.optics_state.channels}
    assert set(names) == {"led", "ring"} and len(set(names.values())) == 2
    assert names["led"].endswith("· led") and names["ring"].endswith("· ring")
