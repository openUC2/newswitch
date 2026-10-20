"""
Camera Manager Protocol

`DetectorManager` covers what every detector offers (exposure, gain, snapshot, live
stream). A camera driven through a camera library (uc2_cam_py) offers more: frame rate,
binning, region of interest, the latest image with its timestamps, the metadata of the
acquisition session and recording to disk. `CameraManager` is that contract; the
dataclasses here carry its values without depending on the library.

Not a rekuest context yet: the actions and the frontend for it follow in a later step.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import numpy as np

from newswitch.protocols.base import Manager

#: Region of interest ``(x, y, width, height)`` in unbinned sensor pixels.
Roi = tuple[int, int, int, int]


@dataclass
class CameraSettings:
    """How to open one camera, and the values to set once it is open.

    Built from the device configuration by `config_io.adapters.cameras`. None means
    "not configured": opening uses the library's default, a setting keeps the camera's
    current value.
    """

    slot: int
    """Detector slot: 1-based position among all detectors of the configuration."""
    key: str
    """Key of the detector in the device configuration."""
    name: str
    manufacturer: str | None = None
    """Vendor as the camera library names it, passed on unchanged."""
    connection_type: str | None = None
    """``"GigE"`` or ``"USB3"``."""
    serial_number: str | None = None
    index: int | None = None
    """Index among the cameras of `connection_type`; not together with `serial_number`."""
    buffer_size: int | None = None
    """Images (slots) in the ring buffer."""
    store_image_data: bool | None = None
    """Record every acquired image to disk."""
    exposure_time_ms: float | None = None
    gain_db: float | None = None
    frame_rate_per_sec: float | None = None
    binning: int | None = None
    vendor_options: dict[str, Any] = field(default_factory=dict)
    """Vendor-specific options, passed on to the library unchanged."""


@dataclass(eq=False)
class CameraFrame:
    """One image of a camera with its timing."""

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
class CameraSessionInfo:
    """Metadata of an acquisition session (one start..stop, one file when recording)."""

    camera_id: str
    """``<model>-<serial>``."""
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
    """Camera settings at the session start (vendor, model, exposure, gain, ROI, ...)."""
    recording_file: str | None
    """File the session is recorded to; None when images are not stored."""

    def wall_time_ns(self, monotonic_ns: int) -> int:
        """Convert a monotonic timestamp of this session to UTC epoch ns.

        Args:
            monotonic_ns: E.g. `CameraFrame.time_ns`.

        Returns:
            UTC nanoseconds since the Unix epoch.
        """
        return self.start_wall_ns + (monotonic_ns - self.start_mono_ns)


@dataclass
class CameraInfo:
    """What a camera is and can do, with its current settings."""

    manufacturer: str
    model: str
    serial_number: str
    connection_type: str
    index: int
    pixel_format: str
    """E.g. ``"Mono8"``, ``"Mono16"``, ``"BayerRG8"``."""
    pixel_count: tuple[int, int]
    """Full, unbinned sensor resolution (x, y)."""
    pixel_pitch_um: tuple[float, float] | None
    pixel_size_um: tuple[float, float] | None
    image_size: tuple[int, int]
    """Current image (width, height) after ROI and binning."""
    buffer_size: int
    is_recording: bool
    """True while images are acquired (into the buffer, and to disk when storing)."""
    recording_file: str | None
    can_set_exposure: bool
    can_set_gain: bool
    can_set_frame_rate: bool
    can_set_binning: bool
    can_set_roi: bool
    range_exposure_time_ms: tuple[float, float] | None
    range_gain_db: tuple[float, float] | None
    range_frame_rate_per_sec: tuple[float, float] | None
    range_binning: list[int]
    exposure_time_ms: float | None
    gain_db: float | None
    frame_rate_per_sec: float | None
    binning: int
    roi: Roi | None
    """None when the complete sensor is read out."""


@runtime_checkable
class CameraManager(Manager, Protocol):
    """Protocol for camera access beyond `DetectorManager`, addressed by detector slot."""

    def get_last_image(self, slot: int) -> CameraFrame | None:
        """Return the most recently acquired image.

        Args:
            slot: Detector slot.

        Returns:
            The image, or None if the camera has not acquired one yet.
        """
        ...

    def get_image_info(self, slot: int) -> CameraSessionInfo | None:
        """Return the metadata of the current or last acquisition session.

        Args:
            slot: Detector slot.

        Returns:
            The session metadata, or None before the first acquisition.
        """
        ...

    def get_camera_info(self, slot: int) -> CameraInfo:
        """Return what the camera is and can do, with its current settings.

        Args:
            slot: Detector slot.
        """
        ...

    def set_frame_rate(self, slot: int, frame_rate_per_sec: float | None) -> float | None:
        """Set the frame rate; None removes the limit.

        Args:
            slot: Detector slot.
            frame_rate_per_sec: Frames per second.

        Returns:
            The frame rate the camera applied.
        """
        ...

    def set_binning(self, slot: int, binning: int) -> int:
        """Set the symmetric hardware binning.

        Args:
            slot: Detector slot.
            binning: Binning factor.

        Returns:
            The binning the camera applied.
        """
        ...

    def set_roi(self, slot: int, roi: Roi | None) -> Roi | None:
        """Set the region of interest; None selects the complete sensor.

        Args:
            slot: Detector slot.
            roi: ``(x, y, width, height)`` in unbinned sensor pixels.

        Returns:
            The region the camera applied.
        """
        ...

    def start_acquisition(self, slot: int) -> None:
        """Keep the camera acquiring until `stop_acquisition` (recorded when storing).

        Args:
            slot: Detector slot.
        """
        ...

    def stop_acquisition(self, slot: int) -> None:
        """End what `start_acquisition` started.

        Args:
            slot: Detector slot.
        """
        ...

    def close(self) -> None:
        """Stop and release all cameras."""
        ...
