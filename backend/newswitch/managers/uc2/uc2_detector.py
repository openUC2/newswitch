"""
UC2 Detector Manager

Detector manager for cameras driven through uc2_cam_py (extra "camera"), one camera per
detector slot. It implements `DetectorManager`, used by the actions, the routines and the
live stream. Importing this module imports uc2_cam_py, so the app imports it only when
cameras are configured (the package `managers.uc2` does not import it).

uc2_cam_py acquires into a ring buffer on a C++ thread; with ``store_image_data`` every
acquired image is also recorded to a ``.uc2rb`` file. A camera acquires as long as anyone
holds it: the live stream, a snapshot, or its debug window. The first holder starts it,
the last one stops it, so a snapshot never ends a live stream. Every start is a new
session (and a new file when recording).

With ``debug_window`` uc2_cam_py shows each camera's newest image in a window of its own
(debugging without the frontend); the cameras are then held from the start, so the window
always has an image.

Each camera's `Detector` is the shared state: it says how to open the camera, the manager
fills in what the camera reports and keeps the current values (including whether it
records) up to date. Those updates take the lock ``camera_parameters`` themselves, as they
also come from the live loop.

Units: the `Detector` state keeps exposure times in seconds, uc2_cam_py in milliseconds.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import koil
import uc2_cam_py

from newswitch.protocols.detector import (
    CameraState,
    Detector,
    DetectorFrame,
    DetectorSessionInfo,
    Roi,
    is_full_sensor,
)

if TYPE_CHECKING:
    from newswitch.broadcasters import FrameBroadcaster

logger = logging.getLogger(__name__)

#: Lock that guards the `Detector` state.
CAMERA_LOCK = "camera_parameters"
#: Holder of a camera while the live loop streams it.
LIVE = "live"
#: Holder of every camera while its debug window is shown (from startup until `close`).
DEBUG = "debug"

#: Pause between two looks into the ring buffer while waiting for an image (s).
POLL_INTERVAL_S = 0.002
#: Pause of the live loop between two rounds, while streaming and while idle (s).
LIVE_INTERVAL_S = 0.01
IDLE_INTERVAL_S = 0.1
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


def _sample_type(pixel_format: str) -> str:
    """numpy dtype uc2_cam_py stores a pixel format in: 8-bit formats uint8, others uint16."""
    return "uint8" if pixel_format.endswith("8") else "uint16"


def _camera_roi(roi: Roi) -> tuple[int, int, int, int] | None:
    """The region as uc2_cam_py takes it: None for the complete sensor (`FULL_SENSOR`).

    Raises:
        ValueError: Not four values.
    """
    x, y, width, height = roi
    return None if is_full_sensor(roi) else (x, y, width, height)


def _mirror(detector: Detector, camera: uc2_cam_py.Camera) -> None:
    """Copy the camera's current settings and recording status into its detector."""
    width, height = camera.image_size
    exposure = camera.exposure_time_ms
    gain = camera.gain_db
    roi = camera.roi
    detector.width, detector.height = width, height
    if exposure is not None:
        detector.current_exposure_time = exposure / 1000.0
    if gain is not None:
        detector.current_gain = gain
    detector.current_frame_rate = camera.frame_rate_per_sec
    detector.current_binning = camera.binning
    detector.current_roi = None if roi is None else list(roi)
    _mirror_recording(detector, camera)


def _mirror_recording(detector: Detector, camera: uc2_cam_py.Camera) -> None:
    """Copy whether the camera acquires, and into which file, into its detector."""
    detector.is_recording = camera.is_recording
    detector.recording_file = camera.recording_file


def _describe(detector: Detector, camera: uc2_cam_py.Camera) -> None:
    """Take over what the camera reports: identity, sensor, ranges, current values."""
    exposure_range = camera.range_exposure_time_ms
    gain_range = camera.range_gain_db
    frame_rate_range = camera.range_frame_rate_per_sec
    pitch = camera.pixel_pitch_um
    size = camera.pixel_size_um
    detector.manufacturer = camera.vendor
    detector.model = camera.model
    detector.serial_number = camera.serial
    detector.connection_type = camera.connection_type
    detector.device_index = camera.index
    detector.buffer_size = camera.buffer_size
    detector.pixel_format = camera.pixel_format
    detector.data_type = _sample_type(camera.pixel_format)
    detector.sensor_width, detector.sensor_height = camera.pixel_count
    detector.pixel_pitch_um = None if pitch is None else pitch[0]
    if size is not None:
        detector.pixel_size_um = size[0]
    if exposure_range is not None:
        detector.min_exposure_time = exposure_range[0] / 1000.0
        detector.max_exposure_time = exposure_range[1] / 1000.0
    if gain_range is not None:
        detector.min_gain, detector.max_gain = gain_range
    detector.min_frame_rate, detector.max_frame_rate = frame_rate_range or (None, None)
    detector.available_binnings = list(camera.range_binning)
    detector.can_set_exposure = camera.can_set_exposure
    detector.can_set_gain = camera.can_set_gain
    detector.can_set_frame_rate = camera.can_set_frame_rate
    detector.can_set_binning = camera.can_set_binning
    detector.can_set_roi = camera.can_set_roi
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

    state: CameraState
    broadcaster: "FrameBroadcaster"

    def __init__(
        self,
        camera_state: CameraState,
        broadcaster: FrameBroadcaster,
        cameras: list[Detector],
        vendor_options: dict[int, dict[str, Any]] | None = None,
        recording_dir: Path | None = None,
        debug_window: bool = False,
    ) -> None:
        """Open the cameras, apply their configured settings and publish their detectors.

        Args:
            camera_state: Shared camera state; its detectors are replaced.
            broadcaster: Frame broadcaster for the live stream.
            cameras: One detector per camera (from `config_io.adapters.cameras`): how to
                open it, the values to set and the name, colormap and exposure presets.
                What the camera reports then replaces its values (identity, sensor, image
                size, current settings, ranges); the detectors become the state.
            vendor_options: Vendor-specific options per slot, passed to uc2_cam_py unchanged.
            recording_dir: Folder for the recordings; None = uc2_cam_py's default.
            debug_window: Show every camera's newest image in a uc2_cam_py window and keep
                the cameras acquiring until `close`. Without an X11 display uc2_cam_py
                only logs an error.

        Raises:
            TypeError, ValueError: Invalid camera settings.
            IndexError, RuntimeError: A camera cannot be found or opened. Cameras opened
                before are closed again.
        """
        self.state = camera_state
        self.broadcaster = broadcaster
        self._closed = False
        self._cameras: dict[int, _OpenCamera] = {}
        # held for a round of the live loop, so stopping cannot interleave with it
        self._live_lock = threading.Lock()
        options = vendor_options or {}
        try:
            for detector in cameras:
                camera = self._open(
                    detector, options.get(detector.slot, {}), recording_dir, debug_window
                )
                self._cameras[detector.slot] = _OpenCamera(detector=detector, camera=camera)
                self._apply(detector, camera)
                _describe(detector, camera)
            if debug_window:  # the window shows the newest image: keep images coming
                for cam in self._cameras.values():
                    self._hold(cam, DEBUG)
        except BaseException:
            self.close()
            raise
        self.state.detectors = list(cameras)

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
            logger=logging.getLogger(f"newswitch.camera.{detector.key}"),
            debug_window=debug_window,
            **options,
        )

    @staticmethod
    def _apply(detector: Detector, camera: uc2_cam_py.Camera) -> None:
        """Write the detector's values (opening a camera does not change its settings).

        Binning first, as it may change the other ranges; the frame rate last, as its
        range may depend on the exposure time. Region and frame rate only when set.
        """
        camera.binning = detector.current_binning
        if detector.current_roi is not None:
            camera.roi = _camera_roi(detector.current_roi)
        camera.exposure_time_ms = detector.current_exposure_time * 1000.0
        camera.gain_db = detector.current_gain
        if detector.current_frame_rate is not None:
            camera.frame_rate_per_sec = detector.current_frame_rate

    # ----------------------------------------------------------------- lookup

    def _open_camera(self, slot: int) -> _OpenCamera:
        """The camera of a slot.

        Raises:
            ValueError: No camera in this slot.
        """
        cam = self._cameras.get(slot)
        if cam is None:
            raise ValueError(f"No camera found with slot {slot}")
        return cam

    def _get_detector(self, slot: int) -> Detector | None:
        """Get a detector by its slot number."""
        for detector in self.state.detectors:
            if detector.slot == slot:
                return detector
        return None

    def _require_detector(self, slot: int) -> Detector:
        """Get a detector by its slot number.

        Raises:
            ValueError: No detector in this slot.
        """
        detector = self._get_detector(slot)
        if detector is None:
            raise ValueError(f"No detector found with slot {slot}")
        return detector

    def _get_active_detector(self, slot: int | None = None) -> Detector | None:
        """Get an active detector by slot or take the first active detector."""
        for detector in self.state.detectors:
            if detector.is_active and (slot is None or detector.slot == slot):
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

    def capture_image(self, slot: int | None = None) -> DetectorFrame:
        """Capture one image exposed after this call.

        The camera runs free (no trigger), so this waits for the first image that reached
        the host at least one exposure time after the call. A camera that is not
        acquiring is started for it and stopped again.

        Args:
            slot: Detector slot number; None = the first active detector.

        Returns:
            The image (an own copy) with its timing.

        Raises:
            ValueError: No active detector with this slot.
            RuntimeError: The manager is closed.
            TimeoutError: No image arrived in time.
        """
        detector = self._get_active_detector(slot)
        if detector is None:
            raise ValueError(f"No active detector found with slot {slot}")
        cam = self._open_camera(detector.slot)
        requested_ns = time.monotonic_ns()
        token = object()
        self._hold(cam, token)
        try:
            return self._wait_for_image(detector.slot, cam.camera, requested_ns)
        finally:
            self._release(cam, token)

    @staticmethod
    def _wait_for_image(slot: int, camera: uc2_cam_py.Camera, requested_ns: int) -> DetectorFrame:
        """Copy the first consistent image that arrived one exposure after `requested_ns`."""
        earliest_ns = requested_ns + int((camera.exposure_time_ms or 0.0) * 1e6)
        timeout_s = _capture_timeout(camera)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            image = camera.get_last_image()
            if image is not None and image.time_before_ns >= earliest_ns:
                data = image.data.copy()
                if image.is_valid():
                    session = camera.get_image_info()
                    return DetectorFrame(
                        slot=slot,
                        data=data,
                        sequence=image.sequence,
                        time_ns=image.time_ns,
                        wall_time_ns=None
                        if session is None
                        else session.wall_time_ns(image.time_ns),
                    )
            time.sleep(POLL_INTERVAL_S)
        raise TimeoutError(f"no image from camera {camera.serial} within {timeout_s:.1f} s")

    def activate_detector(self, slot: int, raise_on_active: bool = False) -> Detector:
        """Activate a detector by its slot number.

        Args:
            slot: Detector slot number.
            raise_on_active: Raise if the detector is active already.

        Returns:
            The activated detector.

        Raises:
            ValueError: No detector in this slot, or it is active and `raise_on_active`.
        """
        detector = self._require_detector(slot)
        if detector.is_active and raise_on_active:
            raise ValueError(f"Detector with slot {slot} is already active")
        detector.is_active = True
        return detector

    def deactivate_detector(self, slot: int) -> None:
        """Deactivate a detector; its camera leaves the live stream at once.

        A camera held for its debug window keeps acquiring.

        Args:
            slot: Detector slot number.

        Raises:
            ValueError: No detector in this slot.
        """
        detector = self._require_detector(slot)
        with self._live_lock:
            detector.is_active = False
            self._release(self._open_camera(slot), LIVE)

    def update_detector(
        self,
        slot: int,
        exposure_time: float | None = None,
        gain: float | None = None,
        frame_rate: float | None = None,
        binning: int | None = None,
        roi: Roi | None = None,
    ) -> Detector:
        """Update detector settings; None keeps a setting. The camera clamps to its ranges.

        Binning first, as it may change the other ranges; the frame rate last, as its
        range may depend on the exposure time. While acquiring, a new binning or region
        restarts the camera with a new session (a new file when storing).

        Args:
            slot: Detector slot number.
            exposure_time: New exposure time in seconds (if provided).
            gain: New gain in dB (if provided).
            frame_rate: New frame rate in frames per second (if provided); 0 removes the
                limit.
            binning: New symmetric binning factor (if provided), snapped to the nearest
                one the camera allows.
            roi: New region of interest (if provided) in unbinned sensor pixels, clamped
                to the sensor and snapped to its grid; `FULL_SENSOR` selects the complete
                sensor.

        Returns:
            The detector with every value the camera applied.

        Raises:
            ValueError: No detector in this slot, exposure <= 0, gain < 0, frame rate < 0,
                binning < 1 or an invalid region.
        """
        detector = self._require_detector(slot)
        cam = self._open_camera(slot)
        camera = cam.camera
        if frame_rate is not None and frame_rate < 0:
            raise ValueError(f"frame rate must be >= 0, got {frame_rate}")
        if binning is not None or roi is not None:
            with cam.lock:
                if binning is not None:
                    camera.binning = binning
                if roi is not None:
                    camera.roi = _camera_roi(roi)
        if exposure_time is not None:
            camera.exposure_time_ms = exposure_time * 1000.0
        if gain is not None:
            camera.gain_db = gain
        if frame_rate is not None:
            camera.frame_rate_per_sec = frame_rate or None
        _mirror(detector, camera)
        return detector

    def get_detector_state(self, slot: int) -> Detector | None:
        """Get the state of a detector: what the camera is and can do, its current settings.

        Args:
            slot: Detector slot number.

        Returns:
            The detector if found, None otherwise.
        """
        return self._get_detector(slot)

    def get_image_info(self, slot: int) -> DetectorSessionInfo | None:
        """Return the metadata of the current or last acquisition session.

        Args:
            slot: Detector slot number.

        Returns:
            The session metadata, or None before the first acquisition.

        Raises:
            ValueError: No camera in this slot.
        """
        camera = self._open_camera(slot).camera
        meta = camera.get_image_info()
        if meta is None:
            return None
        return DetectorSessionInfo(
            detector_id=meta.camera_id,
            width=meta.width,
            height=meta.height,
            channels=meta.channels,
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

    def acquire_live(self) -> None:
        """Stream the active cameras while `CameraState.is_acquiring` is set.

        Runs in the detector background thread until `close`. Holds every active camera
        while streaming and sends each new image (an own copy) to the broadcaster.
        """
        self.broadcaster.start_broadcasting()
        last_sent: dict[int, int] = {}
        while not self._closed:
            streaming = False
            try:
                with self._live_lock:
                    for detector in self.state.detectors:
                        cam = self._cameras.get(detector.slot)
                        if cam is None:
                            continue
                        if self.state.is_acquiring and detector.is_active:
                            if LIVE not in cam.holders:
                                self._hold(cam, LIVE)
                            streaming = True
                            self._send_new_image(detector.slot, cam.camera, last_sent)
                        else:
                            self._release(cam, LIVE)
            except Exception:
                if self._closed:
                    break
                logger.exception("live acquisition failed, retrying in %.0f s", RETRY_INTERVAL_S)
                koil.sleep(RETRY_INTERVAL_S)
                continue
            koil.sleep(LIVE_INTERVAL_S if streaming else IDLE_INTERVAL_S)

    def _send_new_image(
        self, slot: int, camera: uc2_cam_py.Camera, last_sent: dict[int, int]
    ) -> None:
        """Broadcast the camera's latest image unless it was sent already."""
        image = camera.get_last_image()
        if image is None or last_sent.get(slot) == image.time_ns:
            return
        data = image.data.copy()
        if image.is_valid():
            last_sent[slot] = image.time_ns
            self.broadcaster.broadcast_sync(slot, data)

    def stop_acquire_live(self) -> None:
        """Stop the live stream: clear `CameraState.is_acquiring` and release the cameras.

        A camera nobody else holds stops before this returns, so its recording is complete
        on disk; one held for its debug window keeps acquiring. `acquire_live` keeps
        running and streams again once `is_acquiring` is set.
        """
        with self._live_lock:
            self.state.is_acquiring = False
            for cam in self._cameras.values():
                self._release(cam, LIVE)

    def close(self) -> None:
        """Stop and release all cameras, so their recordings are complete on disk.

        Ends `acquire_live`. Calling it again does nothing.
        """
        self._closed = True
        for cam in self._cameras.values():
            with cam.lock:
                cam.holders.clear()
                cam.camera.close()
            cam.detector.is_recording = False
