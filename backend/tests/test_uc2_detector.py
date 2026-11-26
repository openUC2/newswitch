"""Tests for the UC2DetectorManager with uc2_cam_py's simulated camera.

The camera is cam-test's (``instruments/cam-test``, 640 x 480), made fast: a Gaussian spot walks
over the sensor, through the same ring-buffer path as a real camera; ``spot_position(sequence)``
gives its centre per image. Skipped without the extra "camera" (uc2_cam_py).
"""

from __future__ import annotations

import dataclasses
import logging
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest

uc2_cam_py = pytest.importorskip("uc2_cam_py")

from newswitch.drivers import readout  # noqa: E402
from newswitch.drivers.uc2 import uc2_detector  # noqa: E402
from newswitch.drivers.uc2.uc2_detector import UC2DetectorManager, _pixels  # noqa: E402
from newswitch.infra.streaming import FrameBroadcaster  # noqa: E402
from newswitch.instrument import parts as instrument_parts  # noqa: E402
from newswitch.instrument import spec  # noqa: E402
from newswitch.models.devices import AxisWindow, Detector  # noqa: E402
from newswitch.protocols import DetectorManager  # noqa: E402
from newswitch.protocols.frame_sink import FrameSink, I420Sink, NewestOnlySink  # noqa: E402
from newswitch.states.detector import DetectorState  # noqa: E402
from tests.conftest import CAM_TEST  # noqa: E402

#: The camera's detector, as cam-test names it.
NAME = "sim_cam"
#: Its sensor, as (y, x).
PLANE = (480, 640)
#: Vendor options of its simulated camera: cam-test's sensor, but fast.
VENDOR_OPTIONS: dict[str, Any] = {"sensor_width": 640, "sensor_height": 480, "frame_rate": 100.0}

#: ``make_manager(*cameras, debug_window=False, vendor_options=VENDOR_OPTIONS)``
ManagerFactory = Callable[..., UC2DetectorManager]


def camera(binning: int = 1, **values: Any) -> Detector:  # noqa: ANN401
    """A fresh detector of cam-test's camera that does not record, fast and active.

    A detector becomes part of the state of the manager it is given to, so every manager
    gets its own.

    Args:
        binning: How its sensor is binned.
        **values: Detector fields that differ from cam-test's.
    """
    found = instrument_parts.cameras(spec.load(CAM_TEST))
    assert found is not None
    (detector,), _ = found
    fields: dict[str, Any] = {
        "is_active": True,
        "store_image_data": False,
        "current_frame_rate": None,
        "current_gain": 0.0,
        **values,
    }
    detector = dataclasses.replace(detector, **fields)
    readout.apply(detector, [], binning)
    return detector


class RecordingBroadcaster(FrameBroadcaster):
    """Frame broadcaster that keeps what it is sent instead of encoding it."""

    def __init__(self) -> None:
        """Start with nothing sent."""
        super().__init__()
        self.sent: list[tuple[str, np.ndarray]] = []

    def broadcast_sync(self, detector: str, frame: np.ndarray) -> None:
        """Keep the frame."""
        self.sent.append((detector, frame))


class LovekitLikeSink(RecordingBroadcaster):
    """A sink like lovekit's: it says whether it wants a frame, and takes I420 too."""

    i420_width = 320

    def __init__(self, wanted: bool = True) -> None:
        """Wanting every frame, or none."""
        super().__init__()
        self.wanted = wanted
        self.asked = 0
        self.i420: list[tuple[str, int, int, np.ndarray]] = []

    def wants(self, detector: str) -> bool:
        """Whether it wants a frame: as constructed."""
        self.asked += 1
        return self.wanted

    def broadcast_i420(self, detector: str, width: int, height: int, data: np.ndarray) -> None:
        """Keep the I420 frame."""
        self.i420.append((detector, width, height, data))


class Handle:
    """The ring-slot handle of a constructed image: whether its slot still holds it."""

    def __init__(self, valid: bool) -> None:
        """A slot that holds the image, or one the camera overwrote."""
        self.valid = valid

    def still_valid(self) -> bool:
        """Whether the slot still holds the image."""
        return self.valid


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


def stays(count: Callable[[], int], seconds: float = 0.3) -> bool:
    """Whether `count` does not change for `seconds`."""
    before = count()
    time.sleep(seconds)
    return count() == before


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
        ``make_manager(*cameras, debug_window=False, vendor_options=VENDOR_OPTIONS)``; without
        cameras one `camera()`. Every camera gets `vendor_options`.
    """
    made: list[UC2DetectorManager] = []

    def _make(
        *cameras: Detector,
        debug_window: bool = False,
        vendor_options: dict[str, Any] = VENDOR_OPTIONS,
    ) -> UC2DetectorManager:
        detectors = list(cameras) or [camera()]
        manager = UC2DetectorManager(
            detector_state=DetectorState(),
            cameras=detectors,
            vendor_options={detector.name: vendor_options for detector in detectors},
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
    """One manager with one simulated camera (`camera()`)."""
    return make_manager()


def is_recording(manager: UC2DetectorManager) -> bool:
    """Whether the detector says its camera is acquiring."""
    return manager.state.get(NAME).is_recording


def camera_records(manager: UC2DetectorManager) -> bool:
    """Whether the camera is acquiring, asked uc2_cam_py directly."""
    return manager._cameras[NAME].camera.is_recording


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
    cam = manager._cameras[NAME].camera
    assert detector is manager.get_detector_state(NAME)
    assert (detector.name, detector.is_active) == (NAME, True)
    assert (detector.manufacturer, detector.model) == (cam.vendor, cam.model)
    assert (detector.serial_number, detector.connection_type) == ("SIM-0001", cam.connection_type)
    assert (detector.device_index, detector.buffer_size) == (cam.index, 8)
    assert detector.plane() == PLANE
    assert (detector.pixel_format, detector.data_type) == (cam.pixel_format, "uint16")
    assert detector.binning() == 1
    assert all(axis.window_size is None for axis in detector.axes)  # the whole sensor
    assert not detector.is_recording and not camera_records(manager)


def test_configured_values_are_applied(make_manager: ManagerFactory) -> None:
    """Exposure, gain, frame rate and binning of the detector reach the camera."""
    manager = make_manager(
        camera(current_exposure_ms=5.0, current_gain=2.0, current_frame_rate=50.0, binning=2)
    )
    cam = manager._cameras[NAME].camera
    assert (cam.exposure_time_ms, cam.gain_db, cam.frame_rate_per_sec) == (5.0, 2.0, 50.0)
    assert cam.binning == 2
    detector = manager.state.get(NAME)
    assert detector.plane() == (240, 320)
    assert detector.current_exposure_ms == pytest.approx(5.0)
    assert (detector.current_frame_rate, detector.binning()) == (50.0, 2)


def test_configured_detector_keeps_its_name(make_manager: ManagerFactory) -> None:
    """The name stays as configured."""
    (detector,) = make_manager(camera(name="Configured")).state.detectors
    assert detector.name == "Configured"
    assert detector.plane() == PLANE


def test_a_camera_of_another_size_is_refused(make_manager: ManagerFactory) -> None:
    """A camera whose sensor is not the one its detector is described with stops the start."""
    small = {**VENDOR_OPTIONS, "sensor_width": 320, "sensor_height": 240}
    with pytest.raises(ValueError, match="the camera has 320 x 240 pixels"):
        make_manager(vendor_options=small)


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
    detector = manager.update_detector(NAME, exposure_ms=20.0, gain=3.0)
    cam = manager._cameras[NAME].camera
    assert cam.exposure_time_ms == pytest.approx(20.0)
    assert detector.current_exposure_ms == pytest.approx(20.0)
    assert detector.current_gain == pytest.approx(3.0)

    detector = manager.update_detector(NAME, exposure_ms=1_000_000.0)  # far above the range
    assert cam.range_exposure_time_ms is not None
    assert detector.current_exposure_ms == pytest.approx(cam.range_exposure_time_ms[1])

    with pytest.raises(ValueError):
        manager.update_detector(NAME, exposure_ms=0.0)


def test_binning_and_windows_set_the_image_size(manager: UC2DetectorManager) -> None:
    """Binning and windows change the detector's image size to what the camera applied."""
    detector = manager.update_detector(NAME, binning=2)
    assert detector.binning() == 2
    assert detector.plane() == (240, 320)
    manager.update_detector(NAME, binning=1)

    windows = [AxisWindow("x", 0, 100), AxisWindow("y", 0, 50)]
    detector = manager.update_detector(NAME, windows=windows)  # snapped to the pixel grid
    x, y = detector.axis("x"), detector.axis("y")
    assert x.window_size is not None and y.window_size is not None
    assert abs(x.window_size - 100) <= 8 and abs(y.window_size - 50) <= 8
    assert detector.plane() == (y.window_size, x.window_size)
    roi = (x.window_start, y.window_start, x.window_size, y.window_size)
    assert roi == manager._cameras[NAME].camera.roi

    detector = manager.update_detector(NAME, windows=[])  # every axis read whole
    assert all(axis.window_size is None for axis in detector.axes)
    assert detector.plane() == PLANE


def test_frame_rate(manager: UC2DetectorManager) -> None:
    """The frame rate is set; 0 removes the limit, a negative rate is rejected."""
    detector = manager.update_detector(NAME, frame_rate=25.0)
    assert detector.current_frame_rate == pytest.approx(25.0)
    detector = manager.update_detector(NAME, frame_rate=0)
    assert detector.current_frame_rate == manager._cameras[NAME].camera.frame_rate_per_sec
    assert detector.current_frame_rate != pytest.approx(25.0)
    with pytest.raises(ValueError, match="frame rate"):
        manager.update_detector(NAME, frame_rate=-1.0)


# ---------------------------------------------------------------------------
# Images and metadata
# ---------------------------------------------------------------------------


def test_pixels_drops_only_a_single_channel() -> None:
    """uc2_cam_py's (H, W, 1) becomes (H, W) without a copy; nothing else changes."""
    mono = np.zeros((4, 6, 1), dtype=np.uint16)
    assert _pixels(mono).shape == (4, 6) and np.shares_memory(_pixels(mono), mono)
    assert _pixels(np.zeros((1, 6, 1))).shape == (1, 6)  # a one-row region keeps its row
    color = np.zeros((4, 6, 3), dtype=np.uint8)
    assert _pixels(color) is color
    plane = np.zeros((4, 6))
    assert _pixels(plane) is plane


def test_capture_image(make_manager: ManagerFactory) -> None:
    """A snapshot is exposed after the call and leaves a stopped camera stopped."""
    manager = make_manager(camera(current_exposure_ms=50.0))
    started = time.monotonic()
    frame = manager.capture_image(NAME)
    assert time.monotonic() - started >= 0.05
    assert (frame.detector, frame.data.shape, frame.data.dtype) == (NAME, PLANE, np.uint16)
    assert frame.data.max() > 0
    assert not is_recording(manager) and not camera_records(manager)


def test_a_mono_camera_delivers_planes(manager: UC2DetectorManager) -> None:
    """A mono camera's image is (y, x) whatever asks for it; in its ring slot, not copied."""
    assert manager.capture_channels(NAME).shape == PLANE

    frame = manager.capture_frame(NAME)
    assert (frame.height, frame.width, frame.colors) == (*PLANE, 1)
    assert (frame.bytes_per_sample, frame.nbytes) == (2, PLANE[0] * PLANE[1] * 2)
    assert isinstance(frame.keep, uc2_cam_py.ImgData)  # the slot itself, by address
    assert frame.address == frame.keep.data.ctypes.data
    assert frame.valid()


def test_capture_needs_an_active_detector(manager: UC2DetectorManager) -> None:
    """Inactive detectors cannot capture."""
    manager.deactivate_detector(NAME)
    assert manager.list_active_detectors() == []
    with pytest.raises(ValueError, match="No active detector"):
        manager.capture_image(NAME)
    manager.activate_detector(NAME)
    assert manager.capture_image().data.shape == PLANE  # None: the first active detector


def test_captured_image_has_its_timing(manager: UC2DetectorManager) -> None:
    """The image is an own copy with its timing; the spot sits where it should."""
    frame = manager.capture_image(NAME)
    assert frame.data.flags.writeable  # a copy, not the read-only ring slot
    assert frame.wall_time_ns is not None and abs(frame.wall_time_ns - time.time_ns()) < 60e9

    camera = manager._cameras[NAME].camera
    assert isinstance(camera, uc2_cam_py.SimulatedCamera)
    y, x = np.unravel_index(int(np.argmax(frame.data)), frame.data.shape)
    expected_x, expected_y = camera.spot_position(frame.sequence)
    assert abs(x - expected_x) <= 2 and abs(y - expected_y) <= 2


def test_image_info(manager: UC2DetectorManager) -> None:
    """Session metadata exist from the first acquisition on and carry the settings."""
    assert manager.get_image_info(NAME) is None
    manager.update_detector(NAME, exposure_ms=4.0)
    manager.capture_image(NAME)  # a snapshot of a stopped camera is a session of its own
    info = manager.get_image_info(NAME)
    assert info is not None
    assert (info.dims, info.shape, info.dtype) == (["y", "x"], list(PLANE), "uint16")
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
    detector = manager.state.get(NAME)
    assert detector.is_recording and detector.recording_file is not None
    manager.stop_acquire_live()
    assert not is_recording(manager)  # stopped before stop_acquire_live returned
    assert not camera_records(manager)
    info = manager.get_image_info(NAME)
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
    assert {name for name, _ in broadcaster.sent} == {NAME}
    assert all(frame.shape == PLANE for _, frame in broadcaster.sent)
    manager.capture_image(NAME)  # a snapshot during live keeps the camera running
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


def test_live_images_come_by_callback_and_end_with_the_stream(
    make_manager: ManagerFactory,
) -> None:
    """A streaming camera calls back with its images; once the stream or its detector stops, no
    image of it is sent any more."""
    broadcaster = RecordingBroadcaster()
    manager = make_manager()
    cam = manager._cameras[NAME]
    start_live(manager, broadcaster)
    wait_until(lambda: len(broadcaster.sent) >= 3)
    assert cam.live

    manager.stop_acquire_live()
    assert not cam.live
    assert stays(lambda: len(broadcaster.sent))

    manager.state.is_acquiring = True
    sent = len(broadcaster.sent)
    wait_until(lambda: len(broadcaster.sent) >= sent + 3)
    manager.deactivate_detector(NAME)
    assert not cam.live
    assert stays(lambda: len(broadcaster.sent))


def test_live_images_are_at_most_the_live_rate(make_manager: ManagerFactory) -> None:
    """A camera faster than any viewer hands on at most `LIVE_MAX_RATE_HZ` images a second."""
    broadcaster = RecordingBroadcaster()
    manager = make_manager()  # 100 fps
    start_live(manager, broadcaster)
    wait_until(lambda: len(broadcaster.sent) >= 1)
    sent = len(broadcaster.sent)
    time.sleep(1.0)
    assert len(broadcaster.sent) - sent <= uc2_detector.LIVE_MAX_RATE_HZ + 3


def test_live_goes_on_across_a_restart(make_manager: ManagerFactory) -> None:
    """A new binning restarts the camera: its images keep coming, at their new size."""
    broadcaster = RecordingBroadcaster()
    manager = make_manager()
    start_live(manager, broadcaster)
    wait_until(lambda: len(broadcaster.sent) >= 1)
    manager.update_detector(NAME, binning=2)
    wait_until(lambda: broadcaster.sent[-1][1].shape == (240, 320))


def test_a_sink_that_wants_no_frame_gets_none(make_manager: ManagerFactory) -> None:
    """A sink that keeps only the newest frame is asked first; wanting none, it gets none."""
    sink = LovekitLikeSink(wanted=False)
    assert isinstance(sink, NewestOnlySink) and isinstance(sink, I420Sink)
    manager = make_manager()
    start_live(manager, sink)
    wait_until(lambda: sink.asked >= 3)
    assert sink.sent == [] and sink.i420 == []


def test_without_a_native_conversion_an_i420_sink_gets_copies(
    make_manager: ManagerFactory,
) -> None:
    """uc2_cam_py 2.2.2 converts no image to I420 itself: a sink that takes I420 gets copies of
    a Mono8 camera's images, as every other sink."""
    assert not uc2_detector._NATIVE_I420
    sink = LovekitLikeSink()
    manager = make_manager(vendor_options={**VENDOR_OPTIONS, "pixel_format": "Mono8"})
    start_live(manager, sink)
    wait_until(lambda: len(sink.sent) >= 3)
    assert sink.i420 == []
    assert all(frame.shape == PLANE and frame.dtype == np.uint8 for _, frame in sink.sent)


def test_an_overwritten_image_is_dropped(manager: UC2DetectorManager) -> None:
    """An image whose ring slot the camera reused while it was copied is not sent."""
    sink = RecordingBroadcaster()
    cam = manager._cameras[NAME]

    def image(valid: bool) -> Any:  # noqa: ANN401
        data = np.zeros((*PLANE, 1), dtype=np.uint16)
        return uc2_cam_py.ImgData(data, 0, 0, 0, 0, 0, _handle=Handle(valid))

    UC2DetectorManager._send_live(sink, cam, image(valid=False))
    assert sink.sent == []
    UC2DetectorManager._send_live(sink, cam, image(valid=True))
    assert [(name, frame.shape) for name, frame in sink.sent] == [(NAME, PLANE)]


def test_close(manager: UC2DetectorManager) -> None:
    """Closing releases the cameras; closing again does nothing."""
    manager.close()
    manager.close()
    with pytest.raises(RuntimeError, match="closed"):
        manager.capture_image(NAME)


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
    assert manager._cameras[NAME].camera._debug_window is None
    assert not is_recording(manager)


@pytest.mark.usefixtures("no_display")
def test_debug_window_keeps_the_camera_acquiring(
    make_manager: ManagerFactory, caplog: pytest.LogCaptureFixture
) -> None:
    """The flag reaches uc2_cam_py; the camera acquires from the start until close()."""
    with caplog.at_level(logging.ERROR, logger="newswitch.camera"):
        manager = make_manager(debug_window=True)
    camera = manager._cameras[NAME].camera
    assert camera._debug_window is not None and not camera._debug_window.opened
    assert "debug_window=True" in caplog.text  # no display: logged, camera unaffected
    assert is_recording(manager)

    manager.capture_image(NAME)
    manager.stop_acquire_live()
    manager.deactivate_detector(NAME)
    assert is_recording(manager) and camera_records(manager)  # none ends the debug hold

    manager.close()
    assert camera._debug_window is None
    assert not is_recording(manager)
