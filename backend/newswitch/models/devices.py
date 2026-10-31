"""The value types of what delivers images."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Optional

#: Region of interest ``(x, y, width, height)`` in unbinned sensor pixels.
Roi = Sequence[int]


#: Region that selects the complete sensor in `DetectorManager.update_detector`; any region with
#: width or height 0 does the same.
FULL_SENSOR: Roi = (0, 0, 0, 0)


# Built from the instrument, as what can deliver images is read off it; the detector manager then
# fills in what the device reports and keeps the current values up to date. What a manager cannot
# know stays None. The docstrings stay one line: they go into the generated frontend code.
@dataclass
class DetectorAxis:
    """One axis a detector delivers by itself, through its parts and what is wired to it."""

    name: str
    size: Optional[int] = None
    """None: set per acquisition."""
    step: Optional[float] = None
    """In the unit of what delivers it: a stage's z in um."""
    delivered_by: str = ""


@dataclass
class Detector:
    """What delivers images: its name is its cube's."""

    name: str
    width: int
    """Image width after region of interest and binning."""
    height: int
    sensor_width: int
    """Full, unbinned sensor resolution (x)."""
    sensor_height: int
    is_active: bool = False
    data_type: str = "uint16"
    colors: list[str] = field(default_factory=list)
    """A color camera's channels by name (an image each per exposure); empty for a mono one."""
    axes: list[DetectorAxis] = field(default_factory=list)
    """What it delivers by itself."""

    # --- current readout: what the device applied, which its variables then report
    current_exposure_ms: Optional[float] = None
    current_gain: Optional[float] = None
    current_frame_rate: Optional[float] = None
    """Frames per second; None: not limited."""
    current_binning: int = 1
    current_roi: Optional[list[int]] = None
    """``[x, y, width, height]`` in unbinned sensor pixels; None: the complete sensor."""

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
