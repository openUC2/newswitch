"""
Detector Manager Protocol

Defines the protocol for detector/camera control and associated state.

`DetectorManager` covers everything a detector offers: activation, exposure, gain, frame
rate, binning, region of interest, snapshots with their timing, the metadata of the
acquisition session, and the live stream. `Detector` holds all of a detector's values: how
it is configured and opened, what the device reports, its current settings and ranges.
The dataclasses here do not depend on a camera library.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional, Protocol, runtime_checkable

import numpy as np

from newswitch.models.devices import Detector, Roi
from newswitch.protocols.base import Manager
from newswitch.states.detector import CameraState

if TYPE_CHECKING:
    from newswitch.broadcasters import FrameSink


def is_full_sensor(roi: Roi) -> bool:
    """Whether `roi` selects the complete sensor (width or height 0, see `FULL_SENSOR`)."""
    return roi[2] == 0 or roi[3] == 0


@dataclass(eq=False)
class DetectorFrame:
    """One image of a detector with its timing."""

    slot: int
    """Detector slot the image belongs to."""
    data: np.ndarray
    """Pixel data, an own copy: ``(H, W)`` mono or raw Bayer, ``(H, W, 3)`` color."""
    sequence: int
    """Frame index within the acquisition session (0, 1, 2, ...)."""
    time_ns: int
    """Arrival of the image at the host, monotonic ns (`time.monotonic_ns` clock)."""
    wall_time_ns: int | None
    """The same instant as UTC epoch ns; None without session metadata."""


@dataclass
class DetectorSessionInfo:
    """Metadata of an acquisition session (one start..stop, one file when recording)."""

    detector_id: str
    """Identifies the device, e.g. ``<model>-<serial>`` for a camera."""
    width: int
    """Image width after ROI and binning."""
    height: int
    channels: int
    """1 for mono or raw Bayer, 3 for color."""
    dtype: str
    """numpy dtype of the samples, e.g. ``"uint16"``."""
    frame_bytes: int
    slot_count: int
    """Images in the ring buffer."""
    start_wall_ns: int
    """UTC epoch ns at the session start."""
    start_mono_ns: int
    """Monotonic ns at the same instant."""
    settings: dict[str, Any]
    """Detector settings at the session start (vendor, model, exposure, gain, ROI, ...)."""
    recording_file: str | None
    """File the session is recorded to; None when images are not stored."""

    def wall_time_ns(self, monotonic_ns: int) -> int:
        """Convert a monotonic timestamp of this session to UTC epoch ns.

        Args:
            monotonic_ns: E.g. `DetectorFrame.time_ns`.

        Returns:
            UTC nanoseconds since the Unix epoch.
        """
        return self.start_wall_ns + (monotonic_ns - self.start_mono_ns)


@runtime_checkable
class DetectorManager(Manager, Protocol):
    """Protocol defining the interface for detector/camera managers."""

    state: CameraState

    def capture_image(self, slot: int) -> DetectorFrame:
        """Capture a single image from a specific detector.

        A snapshot: the image is exposed after the call.

        Args:
            slot: Detector slot number.

        Returns:
            The image with its timing.
        """
        ...

    def activate_detector(self, slot: int) -> Detector:
        """Activate a detector by its slot number.

        Args:
            slot: Detector slot number from available_detectors.

        Returns:
            The activated detector's state.
        """
        ...

    def deactivate_detector(self, slot: int) -> None:
        """Deactivate a detector by its slot number.

        Args:
            slot: Detector slot number to deactivate.
        """
        ...

    def update_detector(
        self,
        slot: int,
        exposure_time: Optional[float] = None,
        gain: Optional[float] = None,
        frame_rate: Optional[float] = None,
        binning: Optional[int] = None,
        roi: Optional[Roi] = None,
    ) -> Detector:
        """Update detector settings; None keeps a setting.

        The detector clamps the values to its ranges. While acquiring, a new binning or
        region starts a new acquisition session.

        Args:
            slot: Detector slot number.
            exposure_time: New exposure time in seconds (if provided).
            gain: New gain value (if provided).
            frame_rate: New frame rate in frames per second (if provided); 0 removes the
                limit.
            binning: New symmetric binning factor (if provided), snapped to the nearest
                one the detector allows.
            roi: New region of interest (if provided) in unbinned sensor pixels;
                `FULL_SENSOR` selects the complete sensor.

        Returns:
            The updated detector with every value the detector applied.
        """
        ...

    def get_detector_state(self, slot: int) -> Optional[Detector]:
        """Get the state of a detector: what it is and can do, with its current settings.

        Args:
            slot: Detector slot number.

        Returns:
            The detector if found, None otherwise.
        """
        ...

    def get_image_info(self, slot: int) -> Optional[DetectorSessionInfo]:
        """Return the metadata of the current or last acquisition session.

        Args:
            slot: Detector slot number.

        Returns:
            The session metadata, or None before the first acquisition.
        """
        ...

    def list_available_detectors(self) -> list[Detector]:
        """List all available detectors.

        Returns:
            List of available detector configurations.
        """
        ...

    def list_active_detectors(self) -> list[Detector]:
        """List all active detectors.

        Returns:
            List of active detectors.
        """
        ...

    def acquire_live(self, sink: "FrameSink") -> None:
        """Run the live loop until `close`.

        Streams the active detectors to `sink` while `CameraState.is_acquiring` is set;
        setting it starts the live stream.
        """
        ...

    def stop_acquire_live(self) -> None:
        """Stop the live stream now: clear `CameraState.is_acquiring`, end its acquisition.

        `acquire_live` keeps running and streams again once `is_acquiring` is set.
        """
        ...

    def close(self) -> None:
        """End `acquire_live` and release all devices; calling it again does nothing."""
        ...
