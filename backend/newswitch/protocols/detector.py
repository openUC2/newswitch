"""
Detector Manager Protocol

Defines the protocol for detector/camera control and associated state.

`DetectorManager` covers everything a detector offers: activation, exposure, gain, frame
rate, binning, region of interest, snapshots with their timing, the metadata of the
acquisition session, and the live stream. `Detector` holds all of a detector's values: how
it is configured and opened, what the device reports, its current settings and ranges.
The dataclasses here do not depend on a camera library.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable, TYPE_CHECKING
import numpy as np
from rekuest_next.agents.context import context
from rekuest_next import model, state
from enum import Enum
from newswitch.protocols.base import Manager

if TYPE_CHECKING:
    from newswitch.broadcasters import FrameBroadcaster

#: Region of interest ``(x, y, width, height)`` in unbinned sensor pixels.
Roi = Sequence[int]

#: Region that selects the complete sensor in `DetectorManager.update_detector`; any
#: region with width or height 0 does the same.
FULL_SENSOR: Roi = (0, 0, 0, 0)


def is_full_sensor(roi: Roi) -> bool:
    """Whether `roi` selects the complete sensor (width or height 0, see `FULL_SENSOR`)."""
    return roi[2] == 0 or roi[3] == 0


class Colormap(str, Enum):
    """Enumeration of colormap options."""

    RED = "red"
    GREEN = "green"
    BLUE = "blue"


# Built from the device configuration (`config_io.adapters`); the detector manager then
# fills in what the device reports and keeps the current values up to date. Fields a
# manager cannot know stay None. The docstring stays one line: it goes into the generated
# frontend code, and Python 3.12 and 3.13 indent multi-line docstrings differently.
@model
@dataclass
class Detector:
    """Shared state for detector parameters."""

    slot: int = 1
    name: str = "Virtual Camera"
    width: int = 512
    """Image width after region of interest and binning."""
    height: int = 512
    is_active: bool = False
    current_exposure_time: float = 0.1  # seconds
    current_gain: float = 1.0
    current_colormap: Colormap = Colormap.RED

    pixel_size_um: float = 6.5
    """Photosensitive pixel width (x) in um."""
    preset_exposure_times: list[float] = field(
        default_factory=lambda: [0.01, 0.1, 0.5, 1.0, 2.0, 5.0]
    )
    max_exposure_time: float = 10.0
    min_exposure_time: float = 0.001
    max_gain: float = 100.0
    min_gain: float = 0.0
    is_acquiring: bool = False
    data_type: str = "uint8"

    # --- device: from the configuration, replaced by what the device reports once open
    key: Optional[str] = None
    """Key of the detector in the device configuration."""
    manufacturer: Optional[str] = None
    """Vendor as the camera library names it, passed on unchanged."""
    model: Optional[str] = None
    serial_number: Optional[str] = None
    connection_type: Optional[str] = None
    """``"GigE"`` or ``"USB3"`` for a camera; None when no camera is behind the detector."""
    device_index: Optional[int] = None
    """Index among the cameras of `connection_type`; selects the camera when no
    `serial_number` is given (not both)."""
    buffer_size: Optional[int] = None
    """Images (slots) in the ring buffer."""
    store_image_data: Optional[bool] = None
    """True while every acquired image is also written to disk (see `recording_file`);
    switched by `start_acquire_live` / `capture_image` with ``save_to_disk``. None: no
    camera behind the detector."""

    # --- sensor
    pixel_format: Optional[str] = None
    """E.g. ``"Mono8"``, ``"Mono16"``, ``"BayerRG8"``."""
    sensor_width: int = 512
    """Full, unbinned sensor resolution (x)."""
    sensor_height: int = 512
    pixel_pitch_um: Optional[float] = None
    """Centre-to-centre pixel distance (x) in um."""

    # --- current readout
    current_frame_rate: Optional[float] = None
    """Frames per second; None: not limited (before opening: not configured)."""
    current_binning: int = 1
    current_roi: Optional[list[int]] = None
    """``[x, y, width, height]`` in unbinned sensor pixels; None: the complete sensor."""

    # --- ranges and capabilities
    min_frame_rate: Optional[float] = None
    max_frame_rate: Optional[float] = None
    available_binnings: list[int] = field(default_factory=lambda: [1])
    can_set_exposure: bool = True
    can_set_gain: bool = True
    can_set_frame_rate: bool = True
    can_set_binning: bool = True
    can_set_roi: bool = True

    # --- recording
    is_recording: bool = False
    """True while images are acquired (into the buffer, and to disk when storing)."""
    recording_file: Optional[str] = None
    """File the current or last session is recorded to; None when not storing."""


@state(required_locks=["camera_parameters"])
class CameraState:
    """Shared state for camera parameters.

    Default values are set to produce visible images with default illumination.
    Higher exposure and gain ensure the captured images have sufficient
    brightness after uint16→uint8 conversion for PNG output.
    """

    is_acquiring: bool = False
    detectors: list[Detector] = field(default_factory=lambda: [])

    def get_active_detectors(self) -> list[Detector]:
        """Get the currently active detectors."""
        active_detectors: list[Detector] = []
        for detector in self.detectors:
            if detector.is_active:
                active_detectors.append(detector)
        return active_detectors

    def get_detector_for_slot(self, slot: int) -> Detector:
        """Get the detector for a specific slot, if it exists."""
        for detector in self.detectors:
            if detector.slot == slot:
                return detector
        raise ValueError(f"No detector found for slot {slot}")


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


@context(locks=["camera_parameters"])
@runtime_checkable
class DetectorManager(Manager, Protocol):
    """Protocol defining the interface for detector/camera managers."""

    state: CameraState
    broadcaster: "FrameBroadcaster"

    def capture_image(self, slot: int, save_to_disk: bool = False) -> DetectorFrame:
        """Capture a single image from a specific detector.

        A snapshot: the image is exposed after the call.

        Args:
            slot: Detector slot number.
            save_to_disk: Also write the image to disk (`Detector.recording_file`).

        Returns:
            The image with its timing.

        Raises:
            NotImplementedError: ``save_to_disk`` on a detector that cannot record.
            OSError: Recording to disk cannot start (directory, free space).
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

    def acquire_live(self) -> None:
        """Run the live loop until `close`.

        Streams the active detectors to the broadcaster while `CameraState.is_acquiring`
        is set; setting it starts the live stream.
        """
        ...

    def start_acquire_live(self, save_to_disk: bool = False) -> None:
        """Start the live stream: set `CameraState.is_acquiring`.

        Args:
            save_to_disk: The active detectors also write every image to disk, until
                `stop_acquire_live` or until the detector is deactivated. False while
                the stream runs with it switches the writing off.

        Raises:
            NotImplementedError: ``save_to_disk`` on a detector that cannot record.
            OSError: Recording to disk cannot start (directory, free space); the live
                stream is then not started.
        """
        ...

    def stop_acquire_live(self) -> None:
        """Stop the live stream now: clear `CameraState.is_acquiring`, end its acquisition.

        Writing to disk ends with it. `acquire_live` keeps running and streams again once
        the live stream is started.
        """
        ...

    def close(self) -> None:
        """End `acquire_live` and release all devices; calling it again does nothing."""
        ...
