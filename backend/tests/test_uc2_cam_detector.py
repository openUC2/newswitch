"""Tests for the UC2CamDetectorManager with uc2_cam_py's simulated camera.

The simulated camera draws a Gaussian spot that walks over the sensor, through the same
ring-buffer path as a real camera; ``spot_position(sequence)`` gives its centre per image.
Skipped without the extra "camera" (uc2_cam_py).
"""

from __future__ import annotations

import dataclasses
import logging
import threading
import time
from pathlib import Path
from typing import Callable, Iterator

import numpy as np
import pytest
from rekuest_next.state.lock import acquired_locks

uc2_cam_py = pytest.importorskip("uc2_cam_py")

from newswitch.broadcasters import FrameBroadcaster  # noqa: E402
from newswitch.managers.camera import UC2CamDetectorManager  # noqa: E402
from newswitch.protocols import CameraManager, CameraState, DetectorManager  # noqa: E402
from newswitch.protocols.camera import CameraSettings  # noqa: E402
from newswitch.protocols.detector import Colormap, Detector  # noqa: E402

#: A small, fast simulated camera that does not record.
SETTINGS = CameraSettings(
    slot=1,
    key="cam",
    name="Sim",
    manufacturer="Simulated",
    buffer_size=8,
    store_image_data=False,
    vendor_options={"sensor_width": 400, "sensor_height": 200, "frame_rate": 100.0},
)

#: ``make_manager(*settings, broadcaster=None, detectors=None, debug_window=False)``
ManagerFactory = Callable[..., UC2CamDetectorManager]


class RecordingBroadcaster(FrameBroadcaster):
    """Frame broadcaster that keeps what it is sent instead of encoding it."""

    def __init__(self) -> None:
        """Start with nothing sent."""
        super().__init__()
        self.sent: list[tuple[int, np.ndarray]] = []

    def broadcast_sync(self, detector_slot: int, frame: np.ndarray) -> None:
        """Keep the frame."""
        self.sent.append((detector_slot, frame))


def wait_until(condition: Callable[[], bool], timeout: float = 5.0) -> None:
    """Poll `condition` until it holds.

    Raises:
        TimeoutError: It did not hold within `timeout` seconds.
    """
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise TimeoutError("condition not met in time")
        time.sleep(0.005)


@pytest.fixture
def recording_dir(tmp_path: Path) -> Path:
    """Folder the cameras record into."""
    return tmp_path / "recordings"


@pytest.fixture
def make_manager(recording_dir: Path) -> Iterator[ManagerFactory]:
    """Factory for managers on simulated cameras; holds the camera lock, closes them all.

    Args:
        recording_dir: The recording folder fixture.

    Yields:
        ``make_manager(*settings, broadcaster=None, detectors=None, debug_window=False)``;
        without settings one camera with `SETTINGS`.
    """
    made: list[UC2CamDetectorManager] = []

    def _make(
        *settings: CameraSettings,
        broadcaster: FrameBroadcaster | None = None,
        detectors: list[Detector] | None = None,
        debug_window: bool = False,
    ) -> UC2CamDetectorManager:
        manager = UC2CamDetectorManager(
            camera_state=CameraState(),
            broadcaster=broadcaster or FrameBroadcaster(),
            cameras=list(settings) or [SETTINGS],
            detectors=detectors,
            recording_dir=recording_dir,
            debug_window=debug_window,
        )
        made.append(manager)
        return manager

    with acquired_locks("camera_parameters"):
        yield _make
    for manager in made:
        manager.close()


@pytest.fixture
def manager(make_manager: ManagerFactory) -> UC2CamDetectorManager:
    """One manager with one simulated camera (`SETTINGS`) in slot 1."""
    return make_manager()


def is_recording(manager: UC2CamDetectorManager) -> bool:
    """Whether the camera in slot 1 is acquiring."""
    return manager.get_camera_info(1).is_recording


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


def test_satisfies_the_protocols(manager: UC2CamDetectorManager) -> None:
    """The manager is a DetectorManager and a CameraManager."""
    assert isinstance(manager, DetectorManager)
    assert isinstance(manager, CameraManager)


def test_detector_mirrors_the_camera(manager: UC2CamDetectorManager) -> None:
    """The detector takes over size, exposure (in s), gain, their ranges and the sample type."""
    info = manager.get_camera_info(1)
    (detector,) = manager.list_available_detectors()
    assert (detector.slot, detector.name, detector.is_active) == (1, "Sim", True)
    assert (detector.width, detector.height) == (400, 200)
    assert info.exposure_time_ms is not None and info.range_exposure_time_ms is not None
    assert detector.current_exposure_time == pytest.approx(info.exposure_time_ms / 1000.0)
    assert detector.min_exposure_time == pytest.approx(info.range_exposure_time_ms[0] / 1000.0)
    assert detector.max_exposure_time == pytest.approx(info.range_exposure_time_ms[1] / 1000.0)
    assert (detector.min_gain, detector.max_gain) == info.range_gain_db
    assert detector.data_type == "uint16"
    assert info.pixel_size_um is not None and detector.pixel_size_um == info.pixel_size_um[0]


def test_configured_values_are_applied(make_manager: ManagerFactory) -> None:
    """Exposure, gain, frame rate and binning from the configuration reach the camera."""
    settings = dataclasses.replace(
        SETTINGS, exposure_time_ms=5.0, gain_db=2.0, frame_rate_per_sec=50.0, binning=2
    )
    manager = make_manager(settings)
    info = manager.get_camera_info(1)
    assert (info.exposure_time_ms, info.gain_db, info.frame_rate_per_sec) == (5.0, 2.0, 50.0)
    assert info.binning == 2
    detector = manager.state.get_detector_for_slot(1)
    assert (detector.width, detector.height) == (200, 100)
    assert detector.current_exposure_time == pytest.approx(0.005)


def test_configured_detector_keeps_its_presets(make_manager: ManagerFactory) -> None:
    """Name, colormap and presets come from the configuration, the size from the camera."""
    configured = Detector(
        slot=1,
        name="Configured",
        width=1,
        height=1,
        is_active=True,
        current_colormap=Colormap.GREEN,
        preset_exposure_times=[0.001, 0.002],
    )
    (detector,) = make_manager(detectors=[configured]).state.detectors
    assert (detector.name, detector.current_colormap) == ("Configured", Colormap.GREEN)
    assert detector.preset_exposure_times == [0.001, 0.002]
    assert (detector.width, detector.height) == (400, 200)


def test_unknown_vendor_fails(make_manager: ManagerFactory) -> None:
    """A manufacturer the camera library does not know is an error at startup."""
    with pytest.raises(ValueError, match="unknown vendor"):
        make_manager(dataclasses.replace(SETTINGS, manufacturer="NoSuchVendor"))


def test_unknown_slot(manager: UC2CamDetectorManager) -> None:
    """Slots without a camera are rejected."""
    with pytest.raises(ValueError, match="slot 9"):
        manager.get_camera_info(9)
    assert manager.get_detector_state(9) is None


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def test_update_detector(manager: UC2CamDetectorManager) -> None:
    """Exposure in s becomes ms on the camera; the detector shows what the camera applied."""
    detector = manager.update_detector(1, exposure_time=0.02, gain=3.0)
    assert manager.get_camera_info(1).exposure_time_ms == pytest.approx(20.0)
    assert detector.current_exposure_time == pytest.approx(0.02)
    assert detector.current_gain == pytest.approx(3.0)

    detector = manager.update_detector(1, exposure_time=1000.0)  # far above the range
    assert detector.current_exposure_time == pytest.approx(detector.max_exposure_time)

    with pytest.raises(ValueError):
        manager.update_detector(1, exposure_time=0.0)


def test_binning_and_roi_set_the_image_size(manager: UC2CamDetectorManager) -> None:
    """Binning and ROI change the detector's image size to what the camera applied."""
    detector = manager.state.get_detector_for_slot(1)
    assert manager.set_binning(1, 2) == 2
    assert (detector.width, detector.height) == (200, 100)
    assert manager.set_binning(1, 1) == 1

    roi = manager.set_roi(1, (0, 0, 100, 50))  # the camera snaps it to its pixel grid
    assert roi is not None and abs(roi[2] - 100) <= 8 and abs(roi[3] - 50) <= 8
    assert (detector.width, detector.height) == (roi[2], roi[3])
    assert manager.set_roi(1, None) is None
    assert (detector.width, detector.height) == (400, 200)


def test_frame_rate(manager: UC2CamDetectorManager) -> None:
    """The frame rate is set; None removes the limit."""
    assert manager.set_frame_rate(1, 25.0) == pytest.approx(25.0)
    assert manager.set_frame_rate(1, None) is not None


# ---------------------------------------------------------------------------
# Images and metadata
# ---------------------------------------------------------------------------


def test_capture_image(make_manager: ManagerFactory) -> None:
    """A snapshot is exposed after the call and leaves a stopped camera stopped."""
    manager = make_manager(dataclasses.replace(SETTINGS, exposure_time_ms=50.0))
    started = time.monotonic()
    image = manager.capture_image(1)
    assert time.monotonic() - started >= 0.05
    assert (image.shape, image.dtype) == ((200, 400), np.uint16)
    assert image.max() > 0
    assert not is_recording(manager)


def test_capture_needs_an_active_detector(manager: UC2CamDetectorManager) -> None:
    """Inactive detectors cannot capture."""
    manager.deactivate_detector(1)
    assert manager.list_active_detectors() == []
    with pytest.raises(ValueError, match="No active detector"):
        manager.capture_image(1)
    manager.activate_detector(1)
    assert manager.capture_image().shape == (200, 400)  # None: the first active detector


def test_last_image(manager: UC2CamDetectorManager) -> None:
    """The latest image is an own copy with its timing; the spot sits where it should."""
    assert manager.get_last_image(1) is None
    manager.start_acquisition(1)
    wait_until(lambda: manager.get_last_image(1) is not None)
    frame = manager.get_last_image(1)
    assert frame is not None
    assert (frame.slot, frame.data.shape) == (1, (200, 400))
    assert frame.data.flags.writeable  # a copy, not the read-only ring slot
    assert frame.wall_time_ns is not None and abs(frame.wall_time_ns - time.time_ns()) < 60e9

    camera = manager._cameras[1].camera
    assert isinstance(camera, uc2_cam_py.SimulatedCamera)
    y, x = np.unravel_index(int(np.argmax(frame.data)), frame.data.shape)
    expected_x, expected_y = camera.spot_position(frame.sequence)
    assert abs(x - expected_x) <= 2 and abs(y - expected_y) <= 2


def test_image_info(manager: UC2CamDetectorManager) -> None:
    """Session metadata exist from the first acquisition on and carry the settings."""
    assert manager.get_image_info(1) is None
    manager.update_detector(1, exposure_time=0.004)
    manager.start_acquisition(1)
    info = manager.get_image_info(1)
    assert info is not None
    assert (info.width, info.height, info.channels, info.dtype) == (400, 200, 1, "uint16")
    assert info.slot_count == 8
    assert "SIM-0001" in info.camera_id
    assert info.settings["exposure_time_ms"] == pytest.approx(4.0)
    assert info.recording_file is None  # not storing


def test_recording(make_manager: ManagerFactory, recording_dir: Path) -> None:
    """With store_image_data an acquisition session is recorded to a .uc2rb file."""
    manager = make_manager(dataclasses.replace(SETTINGS, store_image_data=True))
    manager.start_acquisition(1)
    wait_until(lambda: (frame := manager.get_last_image(1)) is not None and frame.sequence >= 3)
    manager.stop_acquisition(1)
    info = manager.get_image_info(1)
    assert info is not None and info.recording_file is not None
    recording = Path(info.recording_file)
    assert recording.parent == recording_dir and recording.suffix == ".uc2rb"
    assert recording.stat().st_size > 0
    assert recording.with_suffix(".json").is_file()


def test_snapshot_does_not_end_an_acquisition(manager: UC2CamDetectorManager) -> None:
    """The camera runs while anyone holds it; the last one stops it."""
    manager.start_acquisition(1)
    manager.capture_image(1)
    assert is_recording(manager)
    manager.stop_acquisition(1)
    assert not is_recording(manager)


# ---------------------------------------------------------------------------
# Live stream and shutdown
# ---------------------------------------------------------------------------


def test_live_stream(make_manager: ManagerFactory) -> None:
    """While acquiring, new images are broadcast; stopping and closing end it."""
    broadcaster = RecordingBroadcaster()
    manager = make_manager(broadcaster=broadcaster)
    live = threading.Thread(target=manager.acquire_live, daemon=True)
    live.start()

    manager.state.is_acquiring = True
    wait_until(lambda: len(broadcaster.sent) >= 3)
    assert broadcaster.is_broadcasting
    assert {slot for slot, _ in broadcaster.sent} == {1}
    assert all(frame.shape == (200, 400) for _, frame in broadcaster.sent)
    manager.capture_image(1)  # a snapshot during live keeps the camera running
    assert is_recording(manager)

    manager.state.is_acquiring = False
    wait_until(lambda: not is_recording(manager))

    manager.close()
    live.join(timeout=2.0)
    assert not live.is_alive()


def test_close(manager: UC2CamDetectorManager) -> None:
    """Closing releases the cameras; closing again does nothing."""
    manager.start_acquisition(1)
    manager.close()
    manager.close()
    with pytest.raises(RuntimeError, match="closed"):
        manager.start_acquisition(1)


# ---------------------------------------------------------------------------
# Debug window
# ---------------------------------------------------------------------------


@pytest.fixture
def no_display(monkeypatch: pytest.MonkeyPatch) -> None:
    """No display: uc2_cam_py logs an error instead of opening a window on the screen."""
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)


def test_no_debug_window_by_default(manager: UC2CamDetectorManager) -> None:
    """Without the debug window nothing is shown and the camera waits for a holder."""
    assert manager._cameras[1].camera._debug_window is None
    assert not is_recording(manager)


@pytest.mark.usefixtures("no_display")
def test_debug_window_keeps_the_camera_acquiring(
    make_manager: ManagerFactory, caplog: pytest.LogCaptureFixture
) -> None:
    """The flag reaches uc2_cam_py; the camera acquires from the start until close()."""
    with caplog.at_level(logging.ERROR, logger="newswitch.camera"):
        manager = make_manager(debug_window=True)
    camera = manager._cameras[1].camera
    assert camera._debug_window is not None and not camera._debug_window.opened
    assert "debug_window=True" in caplog.text  # no display: logged, camera unaffected
    assert is_recording(manager)

    manager.capture_image(1)
    manager.start_acquisition(1)
    manager.stop_acquisition(1)
    manager.deactivate_detector(1)
    assert is_recording(manager)  # none of these ends the debug hold

    manager.close()
    assert camera._debug_window is None
