"""
Detector Manager Protocol

Defines the protocol for detector/camera control and associated state.

`DetectorManager` covers everything a detector offers: activation, exposure, gain, frame
rate, binning, the window it reads of each axis, snapshots with their timing, the metadata of the
acquisition session, and the live stream. `Detector` holds all of a detector's values: how
it is configured and opened, what the device reports, its current settings and ranges.
The dataclasses here do not depend on a camera library.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional, Protocol, runtime_checkable

import numpy as np

from newswitch.models.devices import AxisWindow, Detector
from newswitch.protocols.base import Manager
from newswitch.states.detector import DetectorState

if TYPE_CHECKING:
    from newswitch.protocols.frame_sink import FrameSink


@dataclass(eq=False)
class DetectorFrame:
    """One image of a detector with its timing."""

    detector: str
    """The detector the image belongs to."""
    data: np.ndarray
    """Pixel data, an own copy: ``(y, x)``, the detector's image. What it delivers along other
    axes is collapsed into it, colors averaged and arrival times summed: those come from
    `capture_channels`."""
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
    dims: list[str]
    """The axes of an image as it is recorded, e.g. ``["y", "x"]``, ``["y", "x", "c"]``."""
    shape: list[int]
    """Its size along each of `dims`, after windows and binning."""
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
    """Detector settings at the session start (vendor, model, exposure, gain, windows, ...)."""
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

    state: DetectorState

    def capture_channels(self, name: str) -> np.ndarray:
        """Capture one exposure along every axis the detector delivers but ``z``.

        Args:
            name: The detector.

        Returns:
            One value per step of each of its `axes` but ``z``, in their order: ``(c, y, x)``,
            ``(m, y, x)``, ...; a mono camera ``(y, x)``.
        """
        ...

    def capture_stack(self, name: str, planes: int) -> Iterator[np.ndarray]:
        """Capture a stack whose z the detector delivers: each event of it steps the stage.

        Args:
            name: The detector; its `axes` have a ``z``.
            planes: How many planes, starting from where the stage is.

        Yields:
            Each plane as `capture_channels` gives it, while the stage is there.
        """
        ...

    def start_stream(self, name: str) -> None:
        """Start a probe that samples time recording without pause, in blocks.

        Raises:
            ValueError: It samples no time.
        """
        ...

    def read_stream(self, name: str) -> list[np.ndarray]:
        """The whole blocks it recorded since it started, or since the last read: each as
        `capture_channels` would give it, ``(s, ...)``, one after the other with nothing between."""
        ...

    def stop_stream(self, name: str) -> None:
        """Stop it recording: what it has not read is lost."""
        ...

    def capture_image(self, name: str) -> DetectorFrame:
        """Capture a single image from a specific detector.

        A snapshot: the image is exposed after the call.

        Args:
            name: The detector.

        Returns:
            The image with its timing.
        """
        ...

    def activate_detector(self, name: str) -> Detector:
        """Activate a detector by its slot number.

        Args:
            name: The detector from available_detectors.

        Returns:
            The activated detector's state.
        """
        ...

    def deactivate_detector(self, name: str) -> None:
        """Deactivate a detector by its slot number.

        Args:
            name: The detector to deactivate.
        """
        ...

    def update_detector(
        self,
        name: str,
        exposure_ms: Optional[float] = None,
        gain: Optional[float] = None,
        frame_rate: Optional[float] = None,
        binning: Optional[int] = None,
        windows: Optional[list[AxisWindow]] = None,
    ) -> Detector:
        """Update detector settings; None keeps a setting.

        The detector clamps the values to its ranges. While acquiring, a new binning or
        window starts a new acquisition session.

        Args:
            name: The detector.
            exposure_ms: New exposure time in ms (if provided).
            gain: New gain value (if provided).
            frame_rate: New frame rate in frames per second (if provided); 0 removes the
                limit.
            binning: New binning factor of its binnable axes (if provided), snapped to the
                nearest one the detector allows.
            windows: What to read of each axis (if provided), in unbinned steps; an axis
                none names is read whole, so an empty list reads everything.

        Returns:
            The updated detector with every value the detector applied.
        """
        ...

    def plane_under(self, name: str, binning: float | None = None) -> tuple[int, int]:
        """The (y, x) size of its images, at `binning` or the one it has now."""
        ...

    def get_detector_state(self, name: str) -> Optional[Detector]:
        """Get the state of a detector: what it is and can do, with its current settings.

        Args:
            name: The detector.

        Returns:
            The detector if found, None otherwise.
        """
        ...

    def get_image_info(self, name: str) -> Optional[DetectorSessionInfo]:
        """Return the metadata of the current or last acquisition session.

        Args:
            name: The detector.

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

        Streams the active detectors to `sink` while `DetectorState.is_acquiring` is set;
        setting it starts the live stream.
        """
        ...

    def stop_acquire_live(self) -> None:
        """Stop the live stream now: clear `DetectorState.is_acquiring`, end its acquisition.

        `acquire_live` keeps running and streams again once `is_acquiring` is set.
        """
        ...

    def close(self) -> None:
        """End `acquire_live` and release all devices; calling it again does nothing."""
        ...
