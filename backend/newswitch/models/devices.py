"""The value types of what delivers images: a detector, and the axes it measures the sample along."""

from dataclasses import dataclass, field
from typing import Optional


# Built from the instrument, as what can deliver images is read off it; the detector manager then
# fills in what the device reports and keeps the current values up to date. What a manager cannot
# know stays None. The docstrings stay one line: they go into the generated frontend code.
@dataclass
class DetectorAxis:
    """One axis a detector delivers, measuring a domain of the sample: space, spectrum, microtime."""

    name: str
    domain: str
    """What of the sample it measures: space, spectrum, microtime or time."""
    unit: str = ""
    """What `step` is in, native to what delivers it: um of a sensor's pitch, deg of a scan."""
    size: Optional[int] = None
    """All of it, unbinned; None: set per acquisition (the planes of a stack)."""
    step: Optional[float] = None
    delivered_by: str = ""
    binnable: bool = False
    """Whether its steps bin: a sensor's pixels do, a scan's positions do not."""
    window_start: int = 0
    """Where the part read out starts, in unbinned steps."""
    window_size: Optional[int] = None
    """How much is read out, in unbinned steps; None: all of it."""
    binning: int = 1
    delivered_size: Optional[int] = None
    """How many values an image has along it: its window, binned. Kept by `refresh`."""

    def __post_init__(self) -> None:
        """Published from the start."""
        self.refresh()

    def windowed(self) -> Optional[int]:
        """How much of it is read out, unbinned; None when it has no size of its own."""
        return self.size if self.window_size is None else self.window_size

    def delivered(self) -> Optional[int]:
        """How many values an image has along it: its window, binned."""
        windowed = self.windowed()
        return None if windowed is None else windowed // self.binning

    def refresh(self) -> None:
        """Publish `delivered`: called whenever its window or binning changes."""
        self.delivered_size = self.delivered()


@dataclass
class AxisWindow:
    """The part of one axis a detector reads out: from `start`, `size` unbinned steps."""

    axis: str
    start: int
    size: int


@dataclass
class Detector:
    """What delivers images: its name is its cube's."""

    name: str
    is_active: bool = False
    data_type: str = "uint16"
    colors: list[str] = field(default_factory=list)
    """A color camera's channels by name (an image each per exposure); empty for a mono one."""
    axes: list[DetectorAxis] = field(default_factory=list)
    """What it delivers, in the order of a dataset's axes; the image is its last two, y and x."""

    # --- current readout: what the device applied, which its variables then report
    current_exposure_ms: Optional[float] = None
    current_gain: Optional[float] = None
    current_frame_rate: Optional[float] = None
    """Frames per second; None: not limited."""

    def axis(self, name: str) -> DetectorAxis:
        """Its axis called `name`.

        Raises:
            KeyError: It has none.
        """
        for axis in self.axes:
            if axis.name == name:
                return axis
        raise KeyError(f"{self.name} has no axis {name!r}")

    def has_axis(self, name: str) -> bool:
        """Whether it delivers an axis called `name`."""
        return any(axis.name == name for axis in self.axes)

    def plane(self) -> tuple[int, int]:
        """The (y, x) size of its image, after its windows and binning."""
        y, x = self.axis("y").delivered(), self.axis("x").delivered()
        assert y is not None and x is not None
        return y, x

    def binning(self) -> int:
        """How its binnable axes are binned (all alike); 1 when none bins."""
        return next((axis.binning for axis in self.axes if axis.binnable), 1)

    # --- recording
    is_recording: bool = False
    """True while images are acquired (into the buffer, and to disk when storing)."""
    recording_file: Optional[str] = None
    """File the current or last session is recorded to; None when not storing."""

    # --- device: from the description, replaced by what the device reports once open
    manufacturer: Optional[str] = None
    """Vendor as the camera library names it, passed on unchanged."""
    model: Optional[str] = None
    serial_number: Optional[str] = None
    connection_type: Optional[str] = None
    """``"GigE"`` or ``"USB3"`` for a camera; None when no camera is behind the detector."""
    device_index: Optional[int] = None
    """Index among the cameras of `connection_type`; selects the camera when no `serial_number` is
    given (not both)."""
    buffer_size: Optional[int] = None
    """Images (slots) in the ring buffer."""
    store_image_data: Optional[bool] = None
    """Record every acquired image to disk."""
    pixel_format: Optional[str] = None
    """E.g. ``"Mono8"``, ``"Mono16"``, ``"BayerRG8"``."""
