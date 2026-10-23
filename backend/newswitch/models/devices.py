"""The devices' value types: light sources, detectors, objectives, filters."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from arkitekt import model_field

#: Region of interest ``(x, y, width, height)`` in unbinned sensor pixels.
Roi = Sequence[int]


#: Region that selects the complete sensor in `DetectorManager.update_detector`; any
#: region with width or height 0 does the same.
FULL_SENSOR: Roi = (0, 0, 0, 0)


class Colormap(str, Enum):
    """Enumeration of colormap options."""

    RED = "red"
    GREEN = "green"
    BLUE = "blue"


# Built from the device configuration (`config_io.adapters`); the detector manager then
# fills in what the device reports and keeps the current values up to date. Fields a
# manager cannot know stay None. The docstring stays one line: it goes into the generated
# frontend code, and Python 3.12 and 3.13 indent multi-line docstrings differently.
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
    """Record every acquired image to disk."""

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


@dataclass
class Filter:
    """Configuration for a single optical filter.

    Attributes:
        slot: Filter wheel slot number.
        name: Human-readable filter name.
        center_wavelength: Center wavelength of the filter passband (nm).
        bandwidth: Full width at half maximum of the passband (nm).
        transmission: Peak transmission efficiency (0.0 to 1.0).
        is_active: Whether this filter is currently in the light path.
    """

    slot: int = 1
    name: str = "Empty"
    center_wavelength: float = 0.0  # nm - 0 means no filtering (open)
    bandwidth: float = 0.0  # nm - FWHM
    transmission: float = 1.0  # 0.0 to 1.0
    is_active: bool = False


class IlluminationKind(str, Enum):
    """Enumeration of illumination source kinds."""

    LED = "LED"
    LASER = "LASER"
    HALOGEN = "HALOGEN"


@dataclass
class Illumination:
    """A light source: its kind, wavelength (nm), hardware channel, and intensity within
    min..max (the light it gives is intensity / max_intensity of its full power)."""

    kind: IlluminationKind = model_field(default=IlluminationKind.LED)
    slot: int = 1
    intensity: float = 10000.0
    wavelength: float = 0.0
    channel: int = 1
    max_intensity: float = 100000.0
    min_intensity: float = 0.0
    is_active: bool = False


@dataclass
class ObjectiveLens:
    """Configuration for a single objective lens."""

    slot: int
    name: str
    magnification: float
    numerical_aperture: float
    working_distance: float
    binning_factor: int = 1
