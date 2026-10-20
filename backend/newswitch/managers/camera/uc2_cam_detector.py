"""
UC2 Camera Detector Manager

Detector manager for cameras driven through uc2_cam_py, one camera per detector slot. It
implements `DetectorManager` (used by the actions, routines and the live stream) and
`CameraManager` (frame rate, binning, ROI, images with their timing, session metadata,
acquisition sessions).

uc2_cam_py acquires into a ring buffer on a C++ thread; with ``store_image_data`` every
acquired image is also recorded to a ``.uc2rb`` file. A camera acquires as long as anyone
holds it: the live stream, a snapshot, or `start_acquisition`. The first holder starts it,
the last one stops it, so a snapshot never ends a live stream. Every start is a new
session (and a new file when recording).

With ``debug_window`` uc2_cam_py shows each camera's newest image in a window of its own
(debugging without the frontend); the cameras are then held from the start, so the window
always has an image.

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
import numpy as np
import uc2_cam_py

from newswitch.protocols.camera import (
    CameraFrame,
    CameraInfo,
    CameraSessionInfo,
    CameraSettings,
    Roi,
)
from newswitch.protocols.detector import CameraState, Detector

if TYPE_CHECKING:
    from newswitch.broadcasters import FrameBroadcaster

logger = logging.getLogger(__name__)

#: Holder of a camera while the live loop streams it.
LIVE = "live"
#: Holder of a camera between `start_acquisition` and `stop_acquisition`.
EXPLICIT = "explicit"
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
#: Attempts to copy an image before the camera overwrites its buffer slot.
COPY_ATTEMPTS = 5


@dataclass(eq=False)
class _OpenCamera:
    """An opened camera and who currently needs it acquiring."""

    settings: CameraSettings
    camera: uc2_cam_py.Camera
    lock: threading.Lock = field(default_factory=threading.Lock)
    """Serializes starting, stopping and geometry changes."""
    holders: set[object] = field(default_factory=set)


def _sample_type(pixel_format: str) -> str:
    """numpy dtype uc2_cam_py stores a pixel format in: 8-bit formats uint8, others uint16."""
    return "uint8" if pixel_format.endswith("8") else "uint16"


def _mirror(detector: Detector, camera: uc2_cam_py.Camera) -> None:
    """Copy the camera's current image size, exposure and gain into its detector."""
    detector.width, detector.height = camera.image_size
    exposure = camera.exposure_time_ms
    if exposure is not None:
        detector.current_exposure_time = exposure / 1000.0
    gain = camera.gain_db
    if gain is not None:
        detector.current_gain = gain


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


class UC2CamDetectorManager:
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
        cameras: list[CameraSettings],
        detectors: list[Detector] | None = None,
        recording_dir: Path | None = None,
        debug_window: bool = False,
    ) -> None:
        """Open the cameras, apply the configured settings and publish their detectors.

        Args:
            camera_state: Shared camera state; its detectors are replaced.
            broadcaster: Frame broadcaster for the live stream.
            cameras: The cameras to open (from `config_io.adapters.cameras`).
            detectors: Detectors from the configuration (`config_io.adapters.detectors`),
                matched by slot; they provide name, colormap and exposure presets. What the
                camera reports replaces their values: image size, exposure and gain with
                their ranges, pixel size and sample type. A camera without a configured
                detector gets a default one.
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
        configured = {detector.slot: detector for detector in detectors or []}
        published: list[Detector] = []
        try:
            for settings in cameras:
                camera = self._open(settings, recording_dir, debug_window)
                self._cameras[settings.slot] = _OpenCamera(settings=settings, camera=camera)
                self._apply(settings, camera)
                detector = configured.get(settings.slot) or Detector(
                    slot=settings.slot, name=settings.name, is_active=True
                )
                self._describe(detector, camera)
                published.append(detector)
            if debug_window:  # the window shows the newest image: keep images coming
                for cam in self._cameras.values():
                    self._hold(cam, DEBUG)
        except BaseException:
            self.close()
            raise
        self.state.detectors = published

    # ------------------------------------------------------------------ setup

    @staticmethod
    def _open(
        settings: CameraSettings, recording_dir: Path | None, debug_window: bool
    ) -> uc2_cam_py.Camera:
        """Open one camera; values that are not configured keep uc2_cam_py's defaults."""
        options: dict[str, Any] = dict(settings.vendor_options)
        if settings.store_image_data is not None:
            options["store_image_data"] = settings.store_image_data
        return uc2_cam_py.create_camera(
            vendor=settings.manufacturer,
            connection_type=settings.connection_type,
            serial=settings.serial_number,
            index=settings.index,
            buffer_size=settings.buffer_size,
            start_on_init=False,
            image_file_path=recording_dir,
            logger=logging.getLogger(f"newswitch.camera.{settings.key}"),
            debug_window=debug_window,
            **options,
        )

    @staticmethod
    def _apply(settings: CameraSettings, camera: uc2_cam_py.Camera) -> None:
        """Write the configured values (opening a camera does not change its settings).

        Binning first, as it may change the other ranges; the frame rate last, as its
        range may depend on the exposure time.
        """
        if settings.binning is not None:
            camera.binning = settings.binning
        if settings.exposure_time_ms is not None:
            camera.exposure_time_ms = settings.exposure_time_ms
        if settings.gain_db is not None:
            camera.gain_db = settings.gain_db
        if settings.frame_rate_per_sec is not None:
            camera.frame_rate_per_sec = settings.frame_rate_per_sec

    @staticmethod
    def _describe(detector: Detector, camera: uc2_cam_py.Camera) -> None:
        """Take over what the camera reports: limits, pixel size, sample type, current values."""
        exposure_range = camera.range_exposure_time_ms
        if exposure_range is not None:
            detector.min_exposure_time = exposure_range[0] / 1000.0
            detector.max_exposure_time = exposure_range[1] / 1000.0
        gain_range = camera.range_gain_db
        if gain_range is not None:
            detector.min_gain, detector.max_gain = gain_range
        pixel_size = camera.pixel_size_um
        if pixel_size is not None:
            detector.pixel_size_um = pixel_size[0]
        detector.data_type = _sample_type(camera.pixel_format)
        _mirror(detector, camera)

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

    def _release(self, cam: _OpenCamera, holder: object) -> None:
        """Unregister `holder`; the last one stops the acquisition."""
        with cam.lock:
            if holder not in cam.holders:
                return
            cam.holders.discard(holder)
            if not cam.holders and not self._closed:
                cam.camera.stop()

    # ------------------------------------------------------ DetectorManager

    def capture_image(self, slot: int | None = None) -> np.ndarray:
        """Capture one image exposed after this call.

        The camera runs free (no trigger), so this waits for the first image that reached
        the host at least one exposure time after the call. A camera that is not
        acquiring is started for it and stopped again.

        Args:
            slot: Detector slot number; None = the first active detector.

        Returns:
            The image, an own copy.

        Raises:
            ValueError: No active detector with this slot.
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
            return self._wait_for_image(cam.camera, requested_ns)
        finally:
            self._release(cam, token)

    @staticmethod
    def _wait_for_image(camera: uc2_cam_py.Camera, requested_ns: int) -> np.ndarray:
        """Copy the first consistent image that arrived one exposure after `requested_ns`."""
        earliest_ns = requested_ns + int((camera.exposure_time_ms or 0.0) * 1e6)
        timeout_s = _capture_timeout(camera)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            image = camera.get_last_image()
            if image is not None and image.time_before_ns >= earliest_ns:
                data = image.data.copy()
                if image.is_valid():
                    return data
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

        An acquisition started with `start_acquisition` keeps running, and so does a
        camera held for its debug window.

        Args:
            slot: Detector slot number.

        Raises:
            ValueError: No detector in this slot.
        """
        detector = self._require_detector(slot)
        detector.is_active = False
        self._release(self._open_camera(slot), LIVE)

    def update_detector(
        self, slot: int, exposure_time: float | None = None, gain: float | None = None
    ) -> Detector:
        """Set exposure and gain; the camera clamps them to its ranges.

        Args:
            slot: Detector slot number.
            exposure_time: New exposure time in seconds (if provided).
            gain: New gain in dB (if provided).

        Returns:
            The detector with the values the camera applied.

        Raises:
            ValueError: No detector in this slot, exposure <= 0 or gain < 0.
        """
        detector = self._require_detector(slot)
        camera = self._open_camera(slot).camera
        if exposure_time is not None:
            camera.exposure_time_ms = exposure_time * 1000.0
        if gain is not None:
            camera.gain_db = gain
        _mirror(detector, camera)
        return detector

    def get_detector_state(self, slot: int) -> Detector | None:
        """Get the state of a detector.

        Args:
            slot: Detector slot number.

        Returns:
            The detector if found, None otherwise.
        """
        return self._get_detector(slot)

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

    # -------------------------------------------------------- CameraManager

    def get_last_image(self, slot: int) -> CameraFrame | None:
        """Return the most recently acquired image.

        Args:
            slot: Detector slot number.

        Returns:
            The image (an own copy), or None if the camera has not acquired one yet.

        Raises:
            ValueError: No camera in this slot.
            RuntimeError: The camera overwrote the image on every copy attempt (the
                buffer is too small for the frame rate).
        """
        camera = self._open_camera(slot).camera
        for _ in range(COPY_ATTEMPTS):
            image = camera.get_last_image()
            if image is None:
                return None
            data = image.data.copy()
            if image.is_valid():
                session = camera.get_image_info()
                return CameraFrame(
                    slot=slot,
                    data=data,
                    sequence=image.sequence,
                    time_ns=image.time_ns,
                    wall_time_ns=None if session is None else session.wall_time_ns(image.time_ns),
                )
        raise RuntimeError(
            f"camera in slot {slot} overwrote every image while copying it; increase buffer_size"
        )

    def get_image_info(self, slot: int) -> CameraSessionInfo | None:
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
        return CameraSessionInfo(
            camera_id=meta.camera_id,
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

    def get_camera_info(self, slot: int) -> CameraInfo:
        """Return what the camera is and can do, with its current settings.

        Args:
            slot: Detector slot number.

        Raises:
            ValueError: No camera in this slot.
        """
        camera = self._open_camera(slot).camera
        return CameraInfo(
            manufacturer=camera.vendor,
            model=camera.model,
            serial_number=camera.serial,
            connection_type=camera.connection_type,
            index=camera.index,
            pixel_format=camera.pixel_format,
            pixel_count=camera.pixel_count,
            pixel_pitch_um=camera.pixel_pitch_um,
            pixel_size_um=camera.pixel_size_um,
            image_size=camera.image_size,
            buffer_size=camera.buffer_size,
            is_recording=camera.is_recording,
            recording_file=camera.recording_file,
            can_set_exposure=camera.can_set_exposure,
            can_set_gain=camera.can_set_gain,
            can_set_frame_rate=camera.can_set_frame_rate,
            can_set_binning=camera.can_set_binning,
            can_set_roi=camera.can_set_roi,
            range_exposure_time_ms=camera.range_exposure_time_ms,
            range_gain_db=camera.range_gain_db,
            range_frame_rate_per_sec=camera.range_frame_rate_per_sec,
            range_binning=camera.range_binning,
            exposure_time_ms=camera.exposure_time_ms,
            gain_db=camera.gain_db,
            frame_rate_per_sec=camera.frame_rate_per_sec,
            binning=camera.binning,
            roi=camera.roi,
        )

    def set_frame_rate(self, slot: int, frame_rate_per_sec: float | None) -> float | None:
        """Set the frame rate; None removes the limit. The camera clamps it to its range.

        Args:
            slot: Detector slot number.
            frame_rate_per_sec: Frames per second.

        Returns:
            The frame rate the camera applied.

        Raises:
            ValueError: No camera in this slot, or a rate <= 0.
        """
        camera = self._open_camera(slot).camera
        camera.frame_rate_per_sec = frame_rate_per_sec
        return camera.frame_rate_per_sec

    def set_binning(self, slot: int, binning: int) -> int:
        """Set the symmetric hardware binning; updates the detector's image size.

        While acquiring, the camera restarts with a new session (a new file when storing).

        Args:
            slot: Detector slot number.
            binning: Binning factor; snapped to the nearest one the camera allows.

        Returns:
            The binning the camera applied.

        Raises:
            ValueError: No camera in this slot, or a factor < 1.
        """
        detector = self._require_detector(slot)
        cam = self._open_camera(slot)
        with cam.lock:
            cam.camera.binning = binning
        _mirror(detector, cam.camera)
        return cam.camera.binning

    def set_roi(self, slot: int, roi: Roi | None) -> Roi | None:
        """Set the region of interest; updates the detector's image size.

        While acquiring, the camera restarts with a new session (a new file when storing).

        Args:
            slot: Detector slot number.
            roi: ``(x, y, width, height)`` in unbinned sensor pixels, clamped to the sensor;
                None selects the complete sensor.

        Returns:
            The region the camera applied; None for the complete sensor.

        Raises:
            ValueError: No camera in this slot, or an invalid region.
        """
        detector = self._require_detector(slot)
        cam = self._open_camera(slot)
        with cam.lock:
            cam.camera.roi = roi
        _mirror(detector, cam.camera)
        return cam.camera.roi

    def start_acquisition(self, slot: int) -> None:
        """Keep the camera acquiring until `stop_acquisition` (recorded when storing).

        Args:
            slot: Detector slot number.

        Raises:
            ValueError: No camera in this slot.
            RuntimeError: The camera cannot start.
            MemoryError, OSError: uc2_cam_py's buffer or disk-space checks failed.
        """
        self._hold(self._open_camera(slot), EXPLICIT)

    def stop_acquisition(self, slot: int) -> None:
        """End what `start_acquisition` started; other holders keep the camera running.

        Args:
            slot: Detector slot number.

        Raises:
            ValueError: No camera in this slot.
        """
        self._release(self._open_camera(slot), EXPLICIT)

    def close(self) -> None:
        """Stop and release all cameras, so their recordings are complete on disk.

        Ends `acquire_live`. Calling it again does nothing.
        """
        self._closed = True
        for cam in self._cameras.values():
            with cam.lock:
                cam.holders.clear()
                cam.camera.close()
