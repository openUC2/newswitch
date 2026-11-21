"""Tests for choosing the detector manager (`build_detector_manager`) and closing it.

Cameras through uc2_cam_py are used on real hardware only, for what the description's
``hardware.cameras`` names. The test with a real (simulated) uc2_cam_py camera is skipped without
the extra "camera".
"""

from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path
from typing import Literal

import pytest

from newswitch.microscope import parts as microscope
from newswitch.actions.detector import close_detector
from newswitch.infra.streaming import FrameBroadcaster
from newswitch.settings import Settings
from newswitch.drivers.simulated_detector import SimulatedDetectorManager
from newswitch.instrument import spec
from newswitch.microscope.parts import build_detector_manager
from newswitch.protocols import DetectorManager
from newswitch.states.detector import DetectorState
from tests.conftest import run_settings

#: One simulated uc2_cam_py camera and nothing else.
CAM_TEST = Path(__file__).parent.parent / "instruments" / "cam-test"

#: Modules that import uc2_cam_py; removed so a test can make the import fail.
CAMERA_MODULES = (
    "uc2_cam_py",
    "newswitch.drivers.uc2.uc2_detector",
)


@pytest.fixture
def camera_instrument() -> spec.Instrument:
    """The instrument `CAM_TEST`."""
    return spec.load(CAM_TEST)


def _build(config: Settings, instrument: spec.Instrument) -> DetectorManager:
    """Call `build_detector_manager` with a fresh state, at the instrument's initial values."""
    return build_detector_manager(
        config,
        instrument,
        DetectorState(),
        instrument.initial_state,
        lambda name, value: None,
    )


def _settings(
    tmp_path: Path,
    *,
    simulate: Literal["everything", "unwired", "nothing"],
    debug_window: bool = False,
) -> Settings:
    """Settings of `CAM_TEST`, recording into `tmp_path`.

    The debug window is off unless asked for: the description switches it on, and no window may
    pop up during the tests.
    """
    return run_settings(
        tmp_path,
        simulate=simulate,
        instrument=CAM_TEST,
        camera_debug_window=debug_window,
    )


def test_simulated_it_renders_from_the_optics(
    tmp_path: Path, camera_instrument: spec.Instrument
) -> None:
    """Simulated, a wired camera is not opened: newswitch renders what it would see."""
    manager = _build(_settings(tmp_path, simulate="everything"), camera_instrument)
    assert isinstance(manager, SimulatedDetectorManager)
    assert [detector.name for detector in manager.state.detectors] == ["sim_cam"]


def test_missing_camera_library_falls_back(
    tmp_path: Path,
    camera_instrument: spec.Instrument,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Wired cameras without uc2_cam_py: the optics stand in, with a warning."""
    for name in CAMERA_MODULES:
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setitem(sys.modules, "uc2_cam_py", None)  # makes the import fail
    with caplog.at_level(logging.WARNING, logger=microscope.logger.name):
        manager = _build(_settings(tmp_path, simulate="unwired"), camera_instrument)
    assert isinstance(manager, SimulatedDetectorManager)
    assert "uv sync --extra camera" in caplog.text


def test_with_nothing_to_simulate_a_missing_library_stops_the_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    camera_instrument: spec.Instrument,
) -> None:
    """Rendered images would pass for what the camera sees."""
    for name in CAMERA_MODULES:
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setitem(sys.modules, "uc2_cam_py", None)  # makes the import fail
    with pytest.raises(spec.SpecError, match="uv sync --extra camera"):
        _build(_settings(tmp_path, simulate="nothing"), camera_instrument)


def test_real_hardware_opens_the_cameras(
    tmp_path: Path, camera_instrument: spec.Instrument
) -> None:
    """On real hardware wired cameras open through uc2_cam_py; shutdown closes them."""
    pytest.importorskip("uc2_cam_py")
    from newswitch.drivers.uc2.uc2_detector import UC2DetectorManager

    manager = _build(_settings(tmp_path, simulate="nothing"), camera_instrument)
    try:
        assert isinstance(manager, UC2DetectorManager)
        assert isinstance(manager, DetectorManager)
        (detector,) = manager.state.detectors
        assert (detector.name, detector.plane()) == ("sim_cam", (480, 640))  # rows, columns
        assert (detector.serial_number, detector.connection_type) == ("SIM-0001", "USB3")
        assert not detector.is_recording  # no debug window: nobody holds it
    finally:
        close_detector(manager)
    with pytest.raises(RuntimeError, match="closed"):
        manager.capture_image("sim_cam")


def test_camera_debug_window_is_passed_on(
    tmp_path: Path, camera_instrument: spec.Instrument, monkeypatch: pytest.MonkeyPatch
) -> None:
    """camera_debug_window reaches uc2_cam_py, and the camera acquires for the window.

    Without a display, so uc2_cam_py only logs an error instead of opening the window.
    """
    pytest.importorskip("uc2_cam_py")
    from newswitch.drivers.uc2.uc2_detector import UC2DetectorManager

    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    manager = _build(_settings(tmp_path, simulate="nothing", debug_window=True), camera_instrument)
    try:
        assert isinstance(manager, UC2DetectorManager)
        assert manager._cameras["sim_cam"].camera._debug_window is not None
        assert manager.state.get("sim_cam").is_recording
    finally:
        close_detector(manager)


def test_close_detector_ends_the_simulated_live_loop(
    tmp_path: Path, camera_instrument: spec.Instrument
) -> None:
    """The shutdown hook closes any detector manager; a simulated one ends its live loop."""
    manager = _build(_settings(tmp_path, simulate="everything"), camera_instrument)
    live = threading.Thread(target=manager.acquire_live, args=(FrameBroadcaster(),), daemon=True)
    live.start()
    close_detector(manager)
    live.join(timeout=2.0)
    assert not live.is_alive()
