"""What the optics found: for each detector and source, under the current values."""

from dataclasses import dataclass, field
from typing import Optional

from newswitch.models.light_path import LightPath


@dataclass
class DetectorOptics:
    """What a detector sees: as calibrated where that was measured, else as the optics predict."""

    name: str
    sample: str
    """Which sample it sees now: the switches on its way decide."""
    calibrated: bool
    pixel_to_stage: list[list[float]]
    """The sample micrometres of a step along a column, and along a row."""
    pixel_um: float
    """How far apart on the sample two neighbouring pixels look."""
    field_width_um: float
    field_height_um: float
    spot_px: float
    """How blurred a point is, on the detector."""
    expected_counts: float
    """Above the offset, where a bead is, at the current power and exposure."""
    read_noise_counts: float
    depth_of_field_um: float
    """From its objective's NA."""
    defocus_um: float = 0.0
    """How far what focuses it is from where it was last found in focus, or else where it starts."""
    plane_um: float = 0.0
    """Where along the axis what it sees is, in the sample."""
    band_nm: Optional[float] = None
    """The mean wavelength arriving, if any arrives."""
    path: LightPath = field(default_factory=lambda: LightPath(detector=""))


@dataclass
class SourceOptics:
    """How a source's light lands on the sample."""

    name: str
    shape: str
    """A field, a sheet, or a spot the scanner moves."""
    side: Optional[str] = None
    """Where it comes from: epi, transmitted, orthogonal."""
    field_um: Optional[float] = None
    """How wide it lands."""
    thickness_um: Optional[float] = None
    """A sheet's, at its waist."""
    reach_um: Optional[float] = None
    """How far a sheet stays about that thin."""
    along: Optional[str] = None
    """Which way of the image a sheet travels."""
    edge_share: Optional[float] = None
    """How much of a sheet's strength is left at the edge of what is seen."""
    band_nm: Optional[float] = None
    """The mean wavelength it makes arrive at a detector, if it makes any arrive."""
    band_color: Optional[str] = None
    """The colour of the theme that reads as."""


@dataclass
class ChannelSwap:
    """A swap a channel needs in one slot: set otherwise, it is another channel, or none."""

    variable: str
    slot: int
    label: str
    """What is in that slot, as it reads: a filter's name, "mirror", "open"."""


@dataclass
class OpticalChannel:
    """A source whose light gets through a sample to a detector, and the swaps that make it: found,
    and never declared."""

    source: str
    detector: str
    electrons: float
    """At the source's full power and the detector's current exposure, its swaps set."""
    name: str
    """What it is called: inferred from its light path by `channel_names.yml`, apart from the others."""
    description: str
    """The whole of what its light path does, as `channel_names.yml` puts it."""
    sample: str
    """What it is of: which sample its light comes from."""
    band_nm: Optional[float] = None
    swaps: list[ChannelSwap] = field(default_factory=list)
    field_width_um: float = 0.0
    """What the detector sees of the sample, its swaps set."""
    field_height_um: float = 0.0
    depth_of_field_um: float = 0.0
    """How deep what it sees sharply is, through the objective its swaps put on the way."""
