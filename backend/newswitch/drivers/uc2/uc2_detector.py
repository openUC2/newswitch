"""
UC2 Detector Manager

Detector manager for cameras driven through uc2_cam_py (extra "camera"), one camera per
detector. It implements `DetectorManager`, used by the actions, the routines and the
live stream. Importing this module imports uc2_cam_py, so the app imports it only when
cameras are configured (the package `drivers.uc2` does not import it).

uc2_cam_py acquires into a ring buffer on a C++ thread; with ``store_image_data`` every
acquired image is also recorded to a ``.uc2rb`` file. A camera acquires as long as anyone
holds it: the live stream, a snapshot, or its debug window. The first holder starts it,
the last one stops it, so a snapshot never ends a live stream. Every start is a new
session (and a new file when recording).

The live stream does not poll: a streaming camera calls back with each new image
(uc2_cam_py's ``set_image_callback``, on a thread of its own per camera), at most
`LIVE_MAX_RATE_HZ` a second; the live loop only looks after which camera streams.

uc2_cam_py (2.0 and later) delivers every image as ``(H, W, C)``, a single channel (mono, raw
Bayer) with C = 1; `_pixels` makes that ``(y, x)``, so only color comes as ``(y, x, 3)``.

With ``debug_window`` uc2_cam_py shows each camera's newest image in a window of its own
(debugging without the frontend); the cameras are then held from the start, so the window
always has an image.

Each camera's `Detector` is the shared state: it says how to open the camera, the manager
fills in what the camera reports and keeps the current values (including whether it
records) up to date. Those updates take the lock ``camera_parameters`` themselves, as they
also come from the live loop.

Units: exposure times are in milliseconds, as in uc2_cam_py.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any, Optional

import koil
import numpy as np
import uc2_cam_py

from newswitch.drivers import readout as windows_of
from newswitch.models.devices import AxisWindow, Detector
from newswitch.protocols.dataset_store import FrameMemory
from newswitch.protocols.detector import DetectorFrame, DetectorSessionInfo
from newswitch.protocols.frame_sink import FrameSink, I420Sink, NewestOnlySink
from newswitch.states.detector import DetectorState

logger = logging.getLogger(__name__)

#: Lock that guards the `Detector` state.
CAMERA_LOCK = "camera_parameters"
#: Holder of a camera while the live loop streams it.
LIVE = "live"
#: Holder of every camera while its debug window is shown (from startup until `close`).
DEBUG = "debug"
#: Holder of a camera while an acquisition fires each of its frames (`begin_triggered`).
TRIGGERED = "triggered"

#: Pause between two looks into the ring buffer while waiting for an image (s).
POLL_INTERVAL_S = 0.002
#: Pause of the live loop between two looks at which cameras should stream (s). It hands on no
#: images itself: each streaming camera calls back with its new ones (`_send_live`).
LIVE_INTERVAL_S = 0.1
#: Most live images a camera hands its sink per second: what the fastest viewer is sent (the
#: websocket live view's 30 fps; lovekit sends 15). A slower sink gets the newest each time.
LIVE_MAX_RATE_HZ = 30.0
#: Pause of the live loop after a failed round (s).
RETRY_INTERVAL_S = 1.0
#: A snapshot waits at least this long for its image (s).
MIN_CAPTURE_TIMEOUT_S = 2.0


@dataclass(eq=False)
class _OpenCamera:
    """An opened camera, its detector and who currently needs it acquiring."""

    detector: Detector
    camera: uc2_cam_py.Camera
    lock: threading.Lock = field(default_factory=threading.Lock)
    """Serializes starting, stopping and geometry changes."""
    holders: set[object] = field(default_factory=set)
    triggered: bool = False
    """Whether each frame is exposed only when one is captured (its software trigger, fired)."""
    live: bool = False
    """Whether it calls back with each new image for the live stream (`_go_live`)."""


def _pixels(data: np.ndarray) -> np.ndarray:
    """A uc2_cam_py image as newswitch passes it on: (H, W) for mono, (H, W, 3) for colour.

    uc2_cam_py (>= 2.0) always delivers (H, W, C). This drops C for mono (C = 1) as a view,
    without a copy; only the channel axis is squeezed, so a one-pixel-high region keeps its
    row axis. The caller still copies once (the view points into the ring buffer).
    """
    return np.squeeze(data, axis=-1) if data.ndim == 3 and data.shape[-1] == 1 else data


def _sample_type(pixel_format: str) -> str:
    """numpy dtype uc2_cam_py stores a pixel format in: 8-bit formats uint8, others uint16."""
    return "uint8" if pixel_format.endswith("8") else "uint16"


def _camera_roi(windows: list[AxisWindow], detector: Detector) -> tuple[int, int, int, int] | None:
    """The windows of a camera's y and x as the region uc2_cam_py takes: None for all of it."""
    if not windows:
        return None
    by_axis = {window.axis: window for window in windows}
    x, y = detector.axis("x"), detector.axis("y")
    x_window = by_axis.get("x", AxisWindow("x", 0, x.size or 0))
    y_window = by_axis.get("y", AxisWindow("y", 0, y.size or 0))
    return x_window.start, y_window.start, x_window.size, y_window.size


def _windows(detector: Detector) -> list[AxisWindow]:
    """The windows `detector` reads now."""
    return [
        AxisWindow(axis.name, axis.window_start, axis.window_size)
        for axis in detector.axes
        if axis.window_size is not None
    ]


def _mirror(detector: Detector, camera: uc2_cam_py.Camera) -> None:
    """Copy the camera's current settings and recording status into its detector: the region it
    snapped to its grid becomes the windows of y and x."""
    exposure = camera.exposure_time_ms
    gain = camera.gain_db
    roi = camera.roi
    if exposure is not None:
        detector.current_exposure_ms = exposure
    if gain is not None:
        detector.current_gain = gain
    detector.current_frame_rate = camera.frame_rate_per_sec
    windows = (
        [] if roi is None else [AxisWindow("x", roi[0], roi[2]), AxisWindow("y", roi[1], roi[3])]
    )
    windows_of.apply(detector, windows, camera.binning)
    _mirror_recording(detector, camera)


#: Pixel formats a frame is handed to a stream in natively (`ImgData.to_i420`), with whether
#: they are BGR: 8 bits, which need no contrast stretch to be seen. Deeper mono formats keep the
#: stretch of the stream's own conversion (`newswitch.infra.streaming.lovekit.stream_rgba`).
_NATIVE_FORMATS = {"RGB8": False, "BGR8": True, "Mono8": False}

#: Whether uc2_cam_py converts an image to I420 itself (`ImgData.to_i420`). No released version
#: does (2.2.2 has no such method): until one does, every live frame is copied and the sink
#: converts it. The driver's one feature check, made once, so the native path works as soon as
#: uc2_cam_py brings it and cannot fail before.
_NATIVE_I420 = hasattr(uc2_cam_py.ImgData, "to_i420")


def _natively(sink: FrameSink, camera: uc2_cam_py.Camera, colored: bool) -> Optional[bool]:
    """Whether a frame of `camera` goes to `sink` converted natively, and if so whether it is
    BGR; None when it does not (uc2_cam_py cannot, the sink takes no I420, the format needs a
    stretch, or a color camera whose detector is described without colors, which the stream
    shows gray)."""
    if not _NATIVE_I420 or not isinstance(sink, I420Sink):
        return None
    bgr = _NATIVE_FORMATS.get(camera.pixel_format)
    if bgr is None or (camera.pixel_format != "Mono8" and not colored):
        return None
    return bgr


def _plane(data: np.ndarray) -> np.ndarray:
    """A camera's image as ``(y, x)``: a color one's mean of its colors."""
    if data.ndim == 3:
        return np.rint(data.mean(axis=2)).astype(data.dtype)
    return data


def _mirror_recording(detector: Detector, camera: uc2_cam_py.Camera) -> None:
    """Copy whether the camera acquires, and into which file, into its detector."""
    detector.is_recording = camera.is_recording
    detector.recording_file = camera.recording_file


def _describe(detector: Detector, camera: uc2_cam_py.Camera) -> None:
    """Take over what the camera reports: identity, sensor, current values."""
    detector.manufacturer = camera.vendor
    detector.model = camera.model
    detector.serial_number = camera.serial
    detector.connection_type = camera.connection_type
    detector.device_index = camera.index
    detector.buffer_size = camera.buffer_size
    detector.pixel_format = camera.pixel_format
    detector.data_type = _sample_type(camera.pixel_format)
    width, height = camera.pixel_count
    described = (detector.axis("x").size, detector.axis("y").size)
    if (width, height) != described:
        raise ValueError(
            f"{detector.name}: the camera has {width} x {height} pixels, its description "
            f"{described[0]} x {described[1]}"
        )
    _mirror(detector, camera)


def _session_settings(comment: str) -> dict[str, Any]:
    """Parse the settings uc2_cam_py writes as JSON into the session header."""
    try:
        settings = json.loads(comment)
    except ValueError:
        logger.warning("session comment is not JSON: %r", comment)
        return {}
    return settings if isinstance(settings, dict) else {}


def _capture_timeout(camera: uc2_cam_py.Camera) -> float:
    """Seconds a snapshot waits: three frame periods plus exposures, at least the minimum."""
    exposure_s = (camera.exposure_time_ms or 0.0) / 1000.0
    rate = camera.frame_rate_per_sec
    period_s = 1.0 / rate if rate else 0.0
    return max(MIN_CAPTURE_TIMEOUT_S, 3.0 * (period_s + exposure_s))


class UC2DetectorManager:
    """Detector manager for cameras driven through uc2_cam_py.

    All methods are synchronous and thread-safe; the actions run them in a threadpool,
    `acquire_live` runs in the detector background thread.
    """

    #: Called once a value of this part has changed.
    on_change: Callable[[], None] = staticmethod(lambda: None)

    state: DetectorState

    def __init__(
        self,
        detector_state: DetectorState,
        cameras: list[Detector],
        vendor_options: dict[str, dict[str, Any]] | None = None,
        recording_dir: Path | None = None,
        debug_window: bool = False,
    ) -> None:
        """Open the cameras, apply their configured settings and publish their detectors.

        Args:
            detector_state: Shared camera state; its detectors are replaced.
            cameras: One detector per camera (from `instrument.parts.cameras`): how to
                open it, the values to set and the name, colormap and exposure presets.
                What the camera reports then replaces its values (identity, sensor, image
                size, current settings, ranges); the detectors become the state.
            vendor_options: Vendor-specific options per detector, passed to uc2_cam_py unchanged.
            recording_dir: Folder for the recordings; None = uc2_cam_py's default.
            debug_window: Show every camera's newest image in a uc2_cam_py window and keep
                the cameras acquiring until `close`. Without an X11 display uc2_cam_py
                only logs an error.

        Raises:
            TypeError, ValueError: Invalid camera settings.
            IndexError, RuntimeError: A camera cannot be found or opened. Cameras opened
                before are closed again.
        """
        self.state = detector_state
        self._closed = False
        self._cameras: dict[str, _OpenCamera] = {}
        # held for a round of the live loop, so stopping cannot interleave with it
        self._live_lock = threading.Lock()
        options = vendor_options or {}
        try:
            for detector in cameras:
                camera = self._open(
                    detector, options.get(detector.name, {}), recording_dir, debug_window
                )
                self._cameras[detector.name] = _OpenCamera(detector=detector, camera=camera)
                self._apply(detector, camera)
                _describe(detector, camera)
            if debug_window:  # the window shows the newest image: keep images coming
                for cam in self._cameras.values():
                    self._hold(cam, DEBUG)
        except BaseException:
            self.close()
            raise
        self.state.detectors = list(cameras)
        self.state.names = [camera.name for camera in self.state.detectors]

    # ------------------------------------------------------------------ setup

    @staticmethod
    def _open(
        detector: Detector,
        vendor_options: dict[str, Any],
        recording_dir: Path | None,
        debug_window: bool,
    ) -> uc2_cam_py.Camera:
        """Open one camera; values that are not configured keep uc2_cam_py's defaults."""
        options: dict[str, Any] = dict(vendor_options)
        if detector.store_image_data is not None:
            options["store_image_data"] = detector.store_image_data
        return uc2_cam_py.create_camera(
            vendor=detector.manufacturer,
            connection_type=detector.connection_type,
            serial=detector.serial_number,
            index=detector.device_index,
            buffer_size=detector.buffer_size,
            start_on_init=False,
            image_file_path=recording_dir,
            logger=logging.getLogger(f"newswitch.camera.{detector.name}"),
            debug_window=debug_window,
            **options,
        )

    @staticmethod
    def _apply(detector: Detector, camera: uc2_cam_py.Camera) -> None:
        """Write the detector's values (opening a camera does not change its settings).

        Binning first, as it may change the other ranges; the frame rate last, as its
        range may depend on the exposure time. Region and frame rate only when set.
        """
        camera.binning = detector.binning()
        roi = _camera_roi(_windows(detector), detector)
        if roi is not None:
            camera.roi = roi
        camera.exposure_time_ms = detector.current_exposure_ms
        camera.gain_db = detector.current_gain
        if detector.current_frame_rate is not None:
            camera.frame_rate_per_sec = detector.current_frame_rate

    # ----------------------------------------------------------------- lookup

    def _open_camera(self, name: str) -> _OpenCamera:
        """The camera of a detector.

        Raises:
            ValueError: No such camera.
        """
        cam = self._cameras.get(name)
        if cam is None:
            raise ValueError(f"No camera {name}")
        return cam

    def _get_detector(self, name: str) -> Detector | None:
        """The detector called `name`."""
        for detector in self.state.detectors:
            if detector.name == name:
                return detector
        return None

    def _require_detector(self, name: str) -> Detector:
        """The detector called `name`.

        Raises:
            ValueError: No such detector.
        """
        detector = self._get_detector(name)
        if detector is None:
            raise ValueError(f"No detector {name}")
        return detector

    def _get_active_detector(self, name: str | None = None) -> Detector | None:
        """The active detector called `name`, or the first that is on."""
        for detector in self.state.detectors:
            if detector.is_active and (name is None or detector.name == name):
                return detector
        return None

    # ---------------------------------------------------------------- holders

    def _hold(self, cam: _OpenCamera, holder: object) -> None:
        """Register `holder`; the first one starts the acquisition.

        Raises:
            RuntimeError: The manager is closed, or the camera cannot start.
            MemoryError, OSError: uc2_cam_py's buffer or disk-space checks failed.
        """
        with cam.lock:
            if self._closed:
                raise RuntimeError("the camera manager has been closed")
            cam.camera.start()  # does nothing while the camera is acquiring
            cam.holders.add(holder)
            _mirror_recording(cam.detector, cam.camera)

    def _release(self, cam: _OpenCamera, holder: object) -> None:
        """Unregister `holder`; the last one stops the acquisition."""
        with cam.lock:
            if holder not in cam.holders:
                return
            cam.holders.discard(holder)
            if not cam.holders and not self._closed:
                cam.camera.stop()
                _mirror_recording(cam.detector, cam.camera)

    # ------------------------------------------------------ DetectorManager

    def capture_channels(self, name: str) -> np.ndarray:
        """One exposure along every axis but ``z``: a color camera's ``(y, x, 3)`` as ``(c, y, x)``,
        a mono one's ``(y, x)``.

        A raw Bayer format comes back as one mono image: nothing here demosaics it. Colors a
        detector was not described with are averaged, as its image is.
        """
        data = self._capture(name).data
        if data.ndim == 3 and self._require_detector(name).has_axis("c"):
            return np.moveaxis(data, -1, 0)
        return _plane(data)

    def begin_triggered(self, name: str) -> bool:
        """Keep `name`'s camera acquiring, each frame exposed only when one is captured (its
        software trigger, fired by the capture), until `end_triggered`: so a frame is never one
        exposed before it was asked for (while the stage still moved, or the light changed), the
        camera is not started for each, and no frame is sent unasked. False if it has no
        software trigger: captures then wait for a frame of the running camera, as before.
        """
        detector = self._get_active_detector(name)
        if detector is None:
            raise ValueError(f"No active detector {name}")
        cam = self._open_camera(detector.name)
        switch = getattr(cam.camera, "set_software_trigger", None)
        if switch is None or cam.triggered:
            return cam.triggered
        with cam.lock:
            if not switch(True):
                logger.warning("%s: no software trigger, frames are waited for", name)
                return False
            cam.triggered = True
        self._hold(cam, TRIGGERED)
        return True

    def end_triggered(self, name: str) -> None:
        """Let `name`'s camera run free again (`begin_triggered`), and stop it unless another
        needs it."""
        cam = self._cameras.get(name)
        if cam is None or not cam.triggered:
            return
        with cam.lock:
            cam.triggered = False
            try:
                cam.camera.set_software_trigger(False)
            except Exception:  # noqa: BLE001 - the camera is let go of regardless
                logger.exception("%s: could not run free again", name)
        self._release(cam, TRIGGERED)

    @staticmethod
    def _request(cam: _OpenCamera) -> int:
        """When an exposure is asked for: a triggered camera is fired for it, now."""
        requested_ns = time.monotonic_ns()
        if cam.triggered and not cam.camera.fire():
            raise RuntimeError(f"camera {cam.camera.serial} refused its software trigger")
        return requested_ns

    def capture_frame(self, name: str) -> FrameMemory:
        """One exposure, as `capture_channels`, but where the camera put it: its ring slot, by
        address, not copied (a streaming store copies it once, natively). Check `valid` after
        copying: the camera may reuse the slot meanwhile.

        A color camera whose detector is described without colors gives their mean, copied, as
        `capture_channels` does.
        """
        detector = self._get_active_detector(name)
        if detector is None:
            raise ValueError(f"No active detector {name}")
        cam = self._open_camera(detector.name)
        token = object()
        self._hold(cam, token)
        try:
            image = self._wait_for_slot(cam.camera, self._request(cam))
        finally:
            self._release(cam, token)
        data = _pixels(image.data)
        if data.ndim == 3 and not detector.has_axis("c"):
            return FrameMemory.of_array(_plane(np.array(data)))
        height, width = data.shape[:2]
        return FrameMemory(
            address=data.ctypes.data,
            nbytes=data.nbytes,
            height=height,
            width=width,
            colors=data.shape[2] if data.ndim == 3 else 1,
            bytes_per_sample=data.itemsize,
            planar=False,
            keep=image,
            valid=image.is_valid,
            held=cam.triggered,
        )

    @staticmethod
    def _wait_for_slot(camera: uc2_cam_py.Camera, requested_ns: int) -> Any:  # noqa: ANN401
        """The first image that arrived one exposure after `requested_ns`, in its ring slot (a
        view, not copied), consistent when found."""
        earliest_ns = requested_ns + int((camera.exposure_time_ms or 0.0) * 1e6)
        timeout_s = _capture_timeout(camera)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            image = camera.get_last_image()
            if image is not None and image.time_before_ns >= earliest_ns and image.is_valid():
                return image
            time.sleep(POLL_INTERVAL_S)
        raise TimeoutError(f"no image from camera {camera.serial} within {timeout_s:.1f} s")

    def capture_stack(self, name: str, planes: int) -> Iterator[np.ndarray]:
        """The cameras run free, so nothing here can step a stage (`microscope.parts.check_wired`)."""
        raise ValueError(f"Detector {name} delivers no z: no camera is triggered")

    def start_stream(self, name: str) -> None:
        """A camera samples no time of its own: nothing streams here."""
        raise ValueError(f"Detector {name} samples no time: it has nothing to stream")

    def read_stream(self, name: str) -> list[np.ndarray]:
        """Nothing streams here (`start_stream`)."""
        raise ValueError(f"Detector {name} is not streaming")

    def stop_stream(self, name: str) -> None:
        """Nothing streams here (`start_stream`)."""

    def capture_image(self, name: str | None = None) -> DetectorFrame:
        """Capture one image exposed after this call.

        The camera runs free (no trigger), so this waits for the first image that reached
        the host at least one exposure time after the call. A camera that is not
        acquiring is started for it and stopped again.

        Args:
            name: The detector; None = the first active one.

        Returns:
            The image (an own copy) with its timing.

        Raises:
            ValueError: It is not on.
            RuntimeError: The manager is closed.
            TimeoutError: No image arrived in time.
        """
        frame = self._capture(name)
        frame.data = _plane(frame.data)
        return frame

    def _capture(self, name: str | None) -> DetectorFrame:
        """`capture_image`, as the camera delivers it: a color camera's ``(y, x, 3)``."""
        detector = self._get_active_detector(name)
        if detector is None:
            raise ValueError(f"No active detector {name}")
        cam = self._open_camera(detector.name)
        token = object()
        self._hold(cam, token)
        try:
            return self._wait_for_image(detector.name, cam.camera, self._request(cam))
        finally:
            self._release(cam, token)

    @staticmethod
    def _wait_for_image(name: str, camera: uc2_cam_py.Camera, requested_ns: int) -> DetectorFrame:
        """Copy the first consistent image that arrived one exposure after `requested_ns`."""
        earliest_ns = requested_ns + int((camera.exposure_time_ms or 0.0) * 1e6)
        timeout_s = _capture_timeout(camera)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            image = camera.get_last_image()
            if image is not None and image.time_before_ns >= earliest_ns:
                data = _pixels(image.data).copy()
                if image.is_valid():
                    session = camera.get_image_info()
                    return DetectorFrame(
                        detector=name,
                        data=data,
                        sequence=image.sequence,
                        time_ns=image.time_ns,
                        wall_time_ns=None
                        if session is None
                        else session.wall_time_ns(image.time_ns),
                    )
            time.sleep(POLL_INTERVAL_S)
        raise TimeoutError(f"no image from camera {camera.serial} within {timeout_s:.1f} s")

    def activate_detector(self, name: str, raise_on_active: bool = False) -> Detector:
        """Turn a detector on.

        Args:
            name: The detector.
            raise_on_active: Raise if the detector is active already.

        Returns:
            The activated detector.

        Raises:
            ValueError: No such detector, or it is active and `raise_on_active`.
        """
        detector = self._require_detector(name)
        if detector.is_active and raise_on_active:
            raise ValueError(f"Detector {name} is already active")
        detector.is_active = True
        return detector

    def deactivate_detector(self, name: str) -> None:
        """Deactivate a detector; its camera leaves the live stream at once.

        A camera held for its debug window keeps acquiring.

        Args:
            name: The detector.

        Raises:
            ValueError: No such detector.
        """
        detector = self._require_detector(name)
        with self._live_lock:
            detector.is_active = False
            self._leave_live(self._open_camera(name))

    def update_detector(
        self,
        name: str,
        exposure_ms: float | None = None,
        gain: float | None = None,
        frame_rate: float | None = None,
        binning: int | None = None,
        windows: list[AxisWindow] | None = None,
    ) -> Detector:
        """Update detector settings; None keeps a setting. The camera clamps to its ranges.

        Binning first, as it may change the other ranges; the frame rate last, as its
        range may depend on the exposure time. While acquiring, a new binning or window
        restarts the camera with a new session (a new file when storing).

        Args:
            name: The detector.
            exposure_ms: New exposure time in ms (if provided).
            gain: New gain in dB (if provided).
            frame_rate: New frame rate in frames per second (if provided); 0 removes the
                limit.
            binning: New symmetric binning factor (if provided), snapped to the nearest
                one the camera allows.
            windows: What to read of y and x (if provided) in unbinned sensor pixels,
                snapped to the camera's grid; an axis none names is read whole.

        Returns:
            The detector with every value the camera applied.

        Raises:
            ValueError: No such detector, exposure <= 0, gain < 0, frame rate < 0,
                binning < 1 or windows `newswitch.drivers.readout.check_windows` refuses.
        """
        detector = self._require_detector(name)
        cam = self._open_camera(name)
        camera = cam.camera
        if frame_rate is not None and frame_rate < 0:
            raise ValueError(f"frame rate must be >= 0, got {frame_rate}")
        if binning is not None and binning < 1:
            raise ValueError(f"binning must be >= 1, got {binning}")
        if windows is not None:
            windows_of.check_windows(
                detector, windows, detector.binning() if binning is None else binning
            )
        if binning is not None or windows is not None:
            with cam.lock:
                if binning is not None:
                    camera.binning = binning
                if windows is not None:
                    camera.roi = _camera_roi(windows, detector)
        if exposure_ms is not None:
            camera.exposure_time_ms = exposure_ms
        if gain is not None:
            camera.gain_db = gain
        if frame_rate is not None:
            camera.frame_rate_per_sec = frame_rate or None
        _mirror(detector, camera)
        self.on_change()
        return detector

    def plane_under(self, name: str, binning: float | None = None) -> tuple[int, int]:
        """The (y, x) size of its images, at `binning` or the one it has now."""
        detector = self._require_detector(name)
        factor = detector.binning() if binning is None else int(binning)
        y, x = detector.axis("y").windowed() or 0, detector.axis("x").windowed() or 0
        return y // factor, x // factor

    def get_detector_state(self, name: str) -> Detector | None:
        """Get the state of a detector: what the camera is and can do, its current settings.

        Args:
            name: The detector.

        Returns:
            The detector if found, None otherwise.
        """
        return self._get_detector(name)

    def get_image_info(self, name: str) -> DetectorSessionInfo | None:
        """Return the metadata of the current or last acquisition session.

        Args:
            name: The detector.

        Returns:
            The session metadata, or None before the first acquisition.

        Raises:
            ValueError: No such camera.
        """
        camera = self._open_camera(name).camera
        meta = camera.get_image_info()
        if meta is None:
            return None
        return DetectorSessionInfo(
            detector_id=meta.camera_id,
            dims=["y", "x", "c"] if meta.channels > 1 else ["y", "x"],
            shape=[meta.height, meta.width, *([meta.channels] if meta.channels > 1 else [])],
            dtype=meta.dtype,
            frame_bytes=meta.frame_bytes,
            slot_count=meta.slot_count,
            start_wall_ns=meta.start_wall_ns,
            start_mono_ns=meta.start_mono_ns,
            settings=_session_settings(meta.comment),
            recording_file=camera.recording_file,
        )

    def list_available_detectors(self) -> list[Detector]:
        """List all detectors (one per camera)."""
        return self.state.detectors

    def list_active_detectors(self) -> list[Detector]:
        """List all active detectors."""
        return [detector for detector in self.state.detectors if detector.is_active]

    def acquire_live(self, sink: FrameSink) -> None:
        """Stream the active cameras to `sink` while `DetectorState.is_acquiring` is set.

        Runs in the detector background thread until `close`, and only looks after which camera
        streams, every `LIVE_INTERVAL_S`: one that should is held and calls back with each new
        image (`_go_live`), one that should no longer is let go of (`_leave_live`). The images
        themselves never pass through here.
        """
        sink.start_broadcasting()
        while not self._closed:
            try:
                with self._live_lock:
                    for detector in self.state.detectors:
                        cam = self._cameras.get(detector.name)
                        if cam is None:
                            continue
                        if self.state.is_acquiring and detector.is_active:
                            self._go_live(cam, sink)
                        else:
                            self._leave_live(cam)
            except Exception:
                if self._closed:
                    break
                logger.exception("live acquisition failed, retrying in %.0f s", RETRY_INTERVAL_S)
                koil.sleep(RETRY_INTERVAL_S)
                continue
            koil.sleep(LIVE_INTERVAL_S)

    def _go_live(self, cam: _OpenCamera, sink: FrameSink) -> None:
        """Hold `cam` for the live stream and have it call back with each new image (`_send_live`),
        unless it does already.

        Raises:
            RuntimeError: The manager or the camera is closed, or the camera cannot start.
            MemoryError, OSError: uc2_cam_py's buffer or disk-space checks failed.
        """
        if cam.live:
            return
        self._hold(cam, LIVE)
        cam.camera.set_image_callback(
            partial(self._send_live, sink, cam), max_rate_hz=LIVE_MAX_RATE_HZ
        )
        cam.live = True

    def _leave_live(self, cam: _OpenCamera) -> None:
        """Stop `cam` calling back for the live stream and let go of it: once this returns, no
        image of it reaches the sink any more (uc2_cam_py waits for a running call)."""
        if cam.live:
            cam.camera.set_image_callback(None)
            cam.live = False
        self._release(cam, LIVE)

    @staticmethod
    def _send_live(sink: FrameSink, cam: _OpenCamera, image: uc2_cam_py.ImgData) -> None:
        """Hand a new image of `cam` to `sink`, on the camera's callback thread (uc2_cam_py's): each
        image once, the newest, at most `LIVE_MAX_RATE_HZ` a second.

        Takes no lock of the manager's: `_leave_live` holds them while it waits for a running call.
        A sink that keeps only the newest frame says with ``wants`` when it wants none; the image is
        then not copied at all. The image is a view onto its ring slot, which the camera may reuse
        while it is read: it is sent only if `ImgData.is_valid` still holds afterwards, else dropped
        (the next one comes with the next call). An exception here is logged by uc2_cam_py on the
        camera's logger, and the calls go on.
        """
        name = cam.detector.name
        if isinstance(sink, NewestOnlySink) and not sink.wants(name):
            return
        data = _pixels(image.data)
        colored = data.ndim == 3 and cam.detector.has_axis("c")
        native = _natively(sink, cam.camera, colored)
        if native is not None and isinstance(sink, I420Sink):
            # Scaled and converted to I420 natively, straight from the ring slot, without the
            # GIL: no copy of the whole frame, no conversion in Python (`_NATIVE_I420`).
            width, height, i420 = image.to_i420(sink.i420_width, bgr=native)  # type: ignore[attr-defined]
            if image.is_valid():
                sink.broadcast_i420(name, width, height, i420)
            return
        copy = data.copy()
        if image.is_valid():
            # A color camera's live view stays in color when its detector is described in color;
            # what else asks for one image (a snapshot, an autofocus) gets its colors' mean.
            sink.broadcast_sync(name, copy if colored else _plane(copy))

    def stop_acquire_live(self) -> None:
        """Stop the live stream: clear `DetectorState.is_acquiring` and release the cameras.

        No live image reaches the sink once this returns. A camera nobody else holds stops
        before this returns, so its recording is complete on disk; one held for its debug
        window keeps acquiring. `acquire_live` keeps running and streams again once
        `is_acquiring` is set.
        """
        with self._live_lock:
            self.state.is_acquiring = False
            for cam in self._cameras.values():
                self._leave_live(cam)

    def close(self) -> None:
        """Stop and release all cameras, so their recordings are complete on disk.

        Ends `acquire_live`; closing a camera also ends its live callback. Calling it again
        does nothing.
        """
        self._closed = True
        for cam in self._cameras.values():
            with cam.lock:
                cam.holders.clear()
                cam.camera.close()
                cam.live = False
            cam.detector.is_recording = False
