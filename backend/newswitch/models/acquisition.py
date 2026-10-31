"""What an acquisition is asked to do: a multidimensional acquisition, a region scan."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from arkitekt import model_field, withValidator

from newswitch.models.hooks import Hook


class PositionOrder(str, Enum):
    """Defines the order in which stage positions are visited during acquisition."""

    SEQUENTIAL = "sequential"
    RANDOM = "random"


@dataclass
class StreamIllumination:
    """Represents an illumination channel to acquire."""

    source: str  # The source by its name in the instrument (e.g., "laser-488"), or its slot
    wavelength: float  # Wavelength of the illumination in nm
    intensity: float  # Intensity of the illumination (0-1)


@dataclass
class Streams:
    """One lighting of the sample, and the detectors that take an image of it."""

    detectors: list[str] = model_field(
        default_factory=list,
        validators=[
            withValidator(
                "len(value) > 0",
                error_message="We need at least one detector to acquire this stream",
            )
        ],
        description="The detectors that image this stream, by name or slot; each becomes a channel, a color camera one per color",
    )
    mapping: str = model_field(
        default="",
        description="What this stream shows (e.g., 'GFP', 'RFP'): the start of its channels' labels",
    )
    # This is using a validator input, which will run on the frontend to ensure the user has entered at least one illumination with valid intensity before allowing them to start the acquisition
    illuminations: list[StreamIllumination] = model_field(
        default_factory=list,
        validators=[
            withValidator(
                "len(value) > 0",
                error_message="We need at least one illumination channel to acquire this stream",
            )
        ],
        description="List of illuminations to use for this stream (e.g., [{'source': 'LED1', 'wavelength': 488, 'intensity': 0.8}])",
    )


@dataclass
class Stack:
    """Represents a stack of images at different z-slices."""

    z_offset: float  # Offset from the current z position
    z_slices: list[float]  # List of z-slice positions
    z_step: float  # Step size between z-slices
    channels: list[Streams]  # List of channels to acquire at each z-slice
    z_hooks: list[Hook] = model_field(
        default_factory=list,
        description="List of hooks to execute at each z-slice (e.g., 'autofocus', 'z_calibration')",
    )  # List of hooks to execute at each z-slice (e.g., "autofocus", "z_calibration")


@dataclass
class Position:
    """Represents a position in 3D space."""

    x: float
    y: float
    z: float
    stacks: list[Stack]
    p_hooks: list[Hook] = model_field(
        default_factory=list,
        description="List of hooks to execute at each position (e.g., 'autofocus', 'z_calibration')",
    )


@dataclass
class Timepoint:
    """Represents a timepoint in a temporal sequence."""

    time: datetime | None = model_field(
        default=None,
        description="Absolute time to acquire this timepoint (e.g., '2024-01-01T12:00:00') or None to acquire immediately after the previous timepoint",
    )
    positions: list[Position] = model_field(
        default_factory=list,
        description="List of stage positions to acquire at this timepoint",
    )
    position_order: PositionOrder = model_field(
        default=PositionOrder.SEQUENTIAL,
        description="Order in which to visit stage positions (e.g., 'sequential', 'random')",
    )
    t_hooks: list[Hook] = model_field(
        default_factory=list,
        description="List of hooks to execute at each timepoint (e.g., 'autofocus', 'z_calibration')",
    )


@dataclass
class MultidimensionalAcquisition:
    """Configuration for a multidimensional acquisition."""

    timepoints: list[Timepoint] = model_field(
        default_factory=list,
        description="List of timepoints to acquire, each with its own stage positions and hooks",
        validators=[
            withValidator(
                "len(value) > 0",
                error_message="You need at least one timepoint to perform an acquisition",
            )
        ],
    )
    file_name: str = model_field(
        default="acquisition",
        description="Name of the datasets created (e.g., 'experiment1'); with several positions, each ends in its own P<n>",
    )
    m_hooks: list[Hook] = model_field(
        default_factory=list,
        description="List of hooks to execute at the start of the acquisition (e.g., 'autofocus', 'z_calibration')",
    )


@dataclass
class AcquiredDataset:
    """A dataset an acquisition created, in the store it went to."""

    id: str
    name: str
    position: int = model_field(description="Which position of the acquisition it holds, from 0")


class ScanOrder(str, Enum):
    """Defines the order in which stage positions are visited during acquisition."""

    SNAKE_ROW = "SNAKE_ROW"
    SNAKE_COL = "SNAKE_COL"
    RASTER_ROW = "RASTER_ROW"
    RASTER_COL = "RASTER_COL"
