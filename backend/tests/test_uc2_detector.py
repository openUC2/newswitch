"""Tests for the UC2DetectorManager with uc2_cam_py's simulated camera.

The simulated camera draws a Gaussian spot that walks over the sensor, through the same
ring-buffer path as a real camera; ``spot_position(sequence)`` gives its centre per image.
Skipped without the extra "camera" (uc2_cam_py).
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterator

import numpy as np
import pytest

uc2_cam_py = pytest.importorskip("uc2_cam_py")

from newswitch.broadcasters import FrameBroadcaster, FrameSink  # noqa: E402
from newswitch.drivers.uc2.uc2_detector import UC2DetectorManager  # noqa: E402
from newswitch.models.devices import FULL_SENSOR, Detector  # noqa: E402
from newswitch.protocols import DetectorManager  # noqa: E402
from newswitch.states.detector import DetectorState  # noqa: E402

#: Vendor options of the simulated camera: small and fast.
VENDOR_OPTIONS: dict[str, Any] = {"sensor_width": 400, "sensor_height": 200, "frame_rate": 100.0}

#: ``make_manager(*cameras, debug_window=False)``
ManagerFactory = Callable[..., UC2DetectorManager]


def camera(**values: Any) -> Detector:  # noqa: ANN401
    """A fresh detector for a small, fast simulated camera that does not record.

    A detector becomes part of the state of the manager it is given to, so every manager
    gets its own.

    Args:
        **values: Detector fields that differ from the defaults here.
    """
    fields: dict[str, Any] = dict(
        name="Sim",
        width=400,
        height=200,
        sensor_width=400,
        sensor_height=200,
        is_active=True,
        manufacturer="Simulated",
        buffer_size=8,
        store_image_data=False,
        current_exposure_ms=10.0,
        current_gain=0.0,
    )
    fields.update(values)
    return Detector(**fields)


class RecordingBroadcaster(FrameBroadcaster):
    """Frame broadcaster that keeps what it is sent instead of encoding it."""

    def __init__(self) -> None:
        """Start with nothing sent."""
        super().__init__()
        self.sent: list[tuple[str, np.ndarray]] = []

    def broadcast_sync(self, detector: str, frame: np.ndarray) -> None:
        """Keep the frame."""
        self.sent.append((detector, frame))


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
    """Factory for managers on simulated cameras; closes them all.

    Args:
        recording_dir: The recording folder fixture.

    Yields:
        ``make_manager(*cameras, debug_window=False)``; without cameras
        one `camera()`. Every camera gets `VENDOR_OPTIONS`.
    """
    made: list[UC2DetectorManager] = []

    def _make(
        *cameras: Detector,
        debug_window: bool = False,
    ) -> UC2DetectorManager:
        detectors = list(cameras) or [camera()]
        manager = UC2DetectorManager(
            detector_state=DetectorState(),
            cameras=detectors,
            vendor_options={detector.name: VENDOR_OPTIONS for detector in detectors},
            recording_dir=recording_dir,
            debug_window=debug_window,
        )
        made.append(manager)
        return manager

    yield _make
    for manager in made:
        manager.close()


@pytest.fixture
def manager(make_manager: ManagerFactory) -> UC2DetectorManager:
    """One manager with one simulated camera (`camera()`), called Sim."""
    return make_manager()


def is_recording(manager: UC2DetectorManager) -> bool:
    """Whether the detector says its camera is acquiring."""
    return manager.state.get("Sim").is_recording


def camera_records(manager: UC2DetectorManager) -> bool:
    """Whether the camera is acquiring, asked uc2_cam_py directly."""
    return manager._cameras["Sim"].camera.is_recording


def start_live(manager: UC2DetectorManager, sink: FrameSink) -> threading.Thread:
    """Run `acquire_live` in a daemon thread and set `is_acquiring`, as the app does."""
    live = threading.Thread(target=manager.acquire_live, args=(sink,), daemon=True)
    live.start()
    manager.state.is_acquiring = True
    return live


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


def test_satisfies_the_protocol(manager: UC2DetectorManager) -> None:
    """The manager is a DetectorManager."""
    assert isinstance(manager, DetectorManager)


def test_detector_mirrors_the_camera(manager: UC2DetectorManager) -> None:
    """The detector takes over what the camera reports."""
    (detector,) = manager.list_available_detectors()
    cam = manager._cameras["Sim"].camera
    assert detector is manager.get_detector_state("Sim")
    assert (detector.name, detector.is_active) == ("Sim", True)
    assert (detector.manufacturer, detector.model) == (cam.vendor, cam.model)
    assert (detector.serial_number, detector.connection_type) == ("SIM-0001", cam.connection_type)
    assert (detector.device_index, detector.buffer_size) == (cam.index, 8)
    assert (detector.sensor_width, detector.sensor_height) == (400, 200)
    assert (detector.width, detector.height) == (400, 200)
    assert (detector.pixel_format, detector.data_type) == (cam.pixel_format, "uint16")
    assert (detector.current_binning, detector.current_roi) == (1, None)
    assert not detector.is_recording and not camera_records(manager)


def test_configured_values_are_applied(make_manager: ManagerFactory) -> None:
    """Exposure, gain, frame rate and binning of the detector reach the camera."""
    manager = make_manager(
        camera(
            current_exposure_ms=5.0,
            current_gain=2.0,
            current_frame_rate=50.0,
            current_binning=2,
        )
    )
    cam = manager._cameras["Sim"].camera
    assert (cam.exposure_time_ms, cam.gain_db, cam.frame_rate_per_sec) == (5.0, 2.0, 50.0)
    assert cam.binning == 2
    detector = manager.state.get("Sim")
    assert (detector.width, detector.height) == (200, 100)
    assert detector.current_exposure_ms == pytest.approx(5.0)
    assert (detector.current_frame_rate, detector.current_binning) == (50.0, 2)


def test_configured_detector_keeps_its_name(make_manager: ManagerFactory) -> None:
    """The name stays as configured, the size comes from the camera."""
    configured = camera(name="Configured", width=1, height=1)
    (detector,) = make_manager(configured).state.detectors
    assert detector.name == "Configured"
    assert (detector.width, detector.height) == (400, 200)


def test_unknown_vendor_fails(make_manager: ManagerFactory) -> None:
    """A manufacturer the camera library does not know is an error at startup."""
    with pytest.raises(ValueError, match="unknown vendor"):
        make_manager(camera(manufacturer="NoSuchVendor"))


def test_unknown_detector(manager: UC2DetectorManager) -> None:
    """Names without a camera are rejected."""
    with pytest.raises(ValueError, match="No detector nope"):
        manager.update_detector("nope", gain=1.0)
    with pytest.raises(ValueError, match="No camera nope"):
        manager.get_image_info("nope")
    assert manager.get_detector_state("nope") is None


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def test_update_detector(manager: UC2DetectorManager) -> None:
    """Exposure in ms is what the camera takes; the detector shows what the camera applied."""
    detector = manager.update_detector("Sim", exposure_ms=20.0, gain=3.0)
    cam = manager._cameras["Sim"].camera
    assert cam.exposure_time_ms == pytest.approx(20.0)
    assert detector.current_exposure_ms == pytest.approx(20.0)
    assert detector.current_gain == pytest.approx(3.0)

    detector = manager.update_detector("Sim", exposure_ms=1_000_000.0)  # far above the range
    assert cam.range_exposure_time_ms is not None
    assert detector.current_exposure_ms == pytest.approx(cam.range_exposure_time_ms[1])

    with pytest.raises(ValueError):
        manager.update_detector("Sim", exposure_ms=0.0)


def test_binning_and_roi_set_the_image_size(manager: UC2DetectorManager) -> None:
    """Binning and ROI change the detector's image size to what the camera applied."""
    detector = manager.update_detector("Sim", binning=2)
    assert detector.current_binning == 2
    assert (detector.width, detector.height) == (200, 100)
    manager.update_detector("Sim", binning=1)

    detector = manager.update_detector("Sim", roi=(0, 0, 100, 50))  # snapped to the pixel grid
    roi = detector.current_roi
    assert roi is not None and abs(roi[2] - 100) <= 8 and abs(roi[3] - 50) <= 8
    assert (detector.width, detector.height) == (roi[2], roi[3])
    assert roi == list(manager._cameras["Sim"].camera.roi)

    detector = manager.update_detector("Sim", roi=FULL_SENSOR)
    assert detector.current_roi is None
    assert (detector.width, detector.height) == (400, 200)


def test_frame_rate(manager: UC2DetectorManager) -> None:
    """The frame rate is set; 0 removes the limit, a negative rate is rejected."""
    detector = manager.update_detector("Sim", frame_rate=25.0)
    assert detector.current_frame_rate == pytest.approx(25.0)
    detector = manager.update_detector("Sim", frame_rate=0)
    assert detector.current_frame_rate == manager._cameras["Sim"].camera.frame_rate_per_sec
    assert detector.current_frame_rate != pytest.approx(25.0)
    with pytest.raises(ValueError, match="frame rate"):
        manager.update_detector("Sim", frame_rate=-1.0)


# ---------------------------------------------------------------------------
# Images and metadata
# ---------------------------------------------------------------------------


def test_capture_image(make_manager: ManagerFactory) -> None:
    """A snapshot is exposed after the call and leaves a stopped camera stopped."""
    manager = make_manager(camera(current_exposure_ms=50.0))
    started = time.monotonic()
    frame = manager.capture_image("Sim")
    assert time.monotonic() - started >= 0.05
    assert (frame.detector, frame.data.shape, frame.data.dtype) == ("Sim", (200, 400), np.uint16)
    assert frame.data.max() > 0
    assert not is_recording(manager) and not camera_records(manager)


def test_capture_needs_an_active_detector(manager: UC2DetectorManager) -> None:
    """Inactive detectors cannot capture."""
    manager.deactivate_detector("Sim")
    assert manager.list_active_detectors() == []
    with pytest.raises(ValueError, match="No active detector"):
        manager.capture_image("Sim")
    manager.activate_detector("Sim")
    assert manager.capture_image().data.shape == (200, 400)  # None: the first active detector


def test_captured_image_has_its_timing(manager: UC2DetectorManager) -> None:
    """The image is an own copy with its timing; the spot sits where it should."""
    frame = manager.capture_image("Sim")
    assert frame.data.flags.writeable  # a copy, not the read-only ring slot
    assert frame.wall_time_ns is not None and abs(frame.wall_time_ns - time.time_ns()) < 60e9

    camera = manager._cameras["Sim"].camera
    assert isinstance(camera, uc2_cam_py.SimulatedCamera)
    y, x = np.unravel_index(int(np.argmax(frame.data)), frame.data.shape)
    expected_x, expected_y = camera.spot_position(frame.sequence)
    assert abs(x - expected_x) <= 2 and abs(y - expected_y) <= 2


def test_image_info(manager: UC2DetectorManager) -> None:
    """Session metadata exist from the first acquisition on and carry the settings."""
    assert manager.get_image_info("Sim") is None
    manager.update_detector("Sim", exposure_ms=4.0)
    manager.capture_image("Sim")  # a snapshot of a stopped camera is a session of its own
    info = manager.get_image_info("Sim")
    assert info is not None
    assert (info.width, info.height, info.channels, info.dtype) == (400, 200, 1, "uint16")
    assert info.slot_count == 8
    assert "SIM-0001" in info.detector_id
    assert info.settings["exposure_time_ms"] == pytest.approx(4.0)
    assert info.recording_file is None  # not storing


def test_recording(make_manager: ManagerFactory, recording_dir: Path) -> None:
    """With store_image_data the live stream is recorded; stopping it completes the file."""
    broadcaster = RecordingBroadcaster()
    manager = make_manager(camera(store_image_data=True))
    start_live(manager, broadcaster)
    wait_until(lambda: len(broadcaster.sent) >= 3)
    detector = manager.state.get("Sim")
    assert detector.is_recording and detector.recording_file is not None
    manager.stop_acquire_live()
    assert not is_recording(manager)  # stopped before stop_acquire_live returned
    assert not camera_records(manager)
    info = manager.get_image_info("Sim")
    assert info is not None and info.recording_file is not None
    assert detector.recording_file == info.recording_file  # the last session's file
    recording = Path(info.recording_file)
    assert recording.parent == recording_dir and recording.suffix == ".uc2rb"
    assert recording.stat().st_size > 0
    assert recording.with_suffix(".json").is_file()


# ---------------------------------------------------------------------------
# Live stream and shutdown
# ---------------------------------------------------------------------------


def test_live_stream(make_manager: ManagerFactory) -> None:
    """While acquiring, new images are broadcast; stopping and closing end it."""
    broadcaster = RecordingBroadcaster()
    manager = make_manager()
    live = start_live(manager, broadcaster)

    wait_until(lambda: len(broadcaster.sent) >= 3)
    assert broadcaster.is_broadcasting
    assert {name for name, _ in broadcaster.sent} == {"Sim"}
    assert all(frame.shape == (200, 400) for _, frame in broadcaster.sent)
    manager.capture_image("Sim")  # a snapshot during live keeps the camera running
    assert is_recording(manager)

    manager.state.is_acquiring = False  # what the action stop_live_view does
    wait_until(lambda: not is_recording(manager))

    manager.state.is_acquiring = True  # the loop kept running: live starts again
    wait_until(lambda: is_recording(manager))
    manager.stop_acquire_live()
    assert not manager.state.is_acquiring
    assert not is_recording(manager) and not camera_records(manager)

    manager.close()
    live.join(timeout=2.0)
    assert not live.is_alive()


def test_close(manager: UC2DetectorManager) -> None:
    """Closing releases the cameras; closing again does nothing."""
    manager.close()
    manager.close()
    with pytest.raises(RuntimeError, match="closed"):
        manager.capture_image("Sim")


# ---------------------------------------------------------------------------
# Debug window
# ---------------------------------------------------------------------------


@pytest.fixture
def no_display(monkeypatch: pytest.MonkeyPatch) -> None:
    """No display: uc2_cam_py logs an error instead of opening a window on the screen."""
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)


def test_no_debug_window_by_default(manager: UC2DetectorManager) -> None:
    """Without the debug window nothing is shown and the camera waits for a holder."""
    assert manager._cameras["Sim"].camera._debug_window is None
    assert not is_recording(manager)


@pytest.mark.usefixtures("no_display")
def test_debug_window_keeps_the_camera_acquiring(
    make_manager: ManagerFactory, caplog: pytest.LogCaptureFixture
) -> None:
    """The flag reaches uc2_cam_py; the camera acquires from the start until close()."""
    with caplog.at_level(logging.ERROR, logger="newswitch.camera"):
        manager = make_manager(debug_window=True)
    camera = manager._cameras["Sim"].camera
    assert camera._debug_window is not None and not camera._debug_window.opened
    assert "debug_window=True" in caplog.text  # no display: logged, camera unaffected
    assert is_recording(manager)

    manager.capture_image("Sim")
    manager.stop_acquire_live()
    manager.deactivate_detector("Sim")
    assert is_recording(manager) and camera_records(manager)  # none ends the debug hold

    manager.close()
    assert camera._debug_window is None
    assert not is_recording(manager)
