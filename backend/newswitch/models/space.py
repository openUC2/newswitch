"""Where things are, as mikro says it: coordinate systems of named axes, and the maps between them.

A transformation is one of mikro's kinds (`newswitch.instrument.space` composes them). A
BY_DIMENSION is parts side by side, each mapping its own input axes onto its own output axes; an
axis no part names is one it says nothing about. So a camera's columns and rows are placed while its
colors are not, and a thermometer, which has no axes at all, is placed at one point.
"""

from dataclasses import dataclass, field
from typing import Optional

from newswitch.models.light_path import AffineMatrix

#: The 4x4 that changes nothing.
IDENTITY: AffineMatrix = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
]


@dataclass
class Axis:
    """One axis of a coordinate system: its name, what it is (mikro's AxisType), and its unit."""

    name: str
    type: str
    """SPACE, TIME, CHANNEL, SPECTRUM or MICROTIME."""
    unit: str = ""
    """What a position along it is in; empty: indices, as of an array."""


@dataclass
class CoordinateSystem:
    """A node of the graph: a frame, by name, and the axes a position in it has."""

    name: str
    axes: list[Axis] = field(default_factory=list)
    """None: a point, such as where a thermometer measures."""


@dataclass
class DimensionPart:
    """One part of a BY_DIMENSION: its own input axes onto its own output axes, by one kind."""

    kind: str
    """IDENTITY, SCALE, TRANSLATION or AFFINE."""
    input_axes: list[str]
    output_axes: list[str]
    scale: Optional[list[float]] = None
    """SCALE: one factor per input axis."""
    translation: Optional[list[float]] = None
    """TRANSLATION: one offset per input axis."""
    affine: Optional[list[list[float]]] = None
    """AFFINE: a row per output axis, a column per input axis and then the offset."""


@dataclass
class Transformation:
    """An edge of the graph, from `input` to `output`, of one of mikro's kinds."""

    input: str
    output: str
    kind: str
    """IDENTITY, SCALE, TRANSLATION, AFFINE or BY_DIMENSION."""
    name: str = ""
    """What made it: mount, pixels, place, image."""
    scale: Optional[list[float]] = None
    translation: Optional[list[float]] = None
    affine: Optional[list[list[float]]] = None
    """A row per axis of `output`, a column per axis of `input` and then the offset."""
    parts: list[DimensionPart] = field(default_factory=list)
    """BY_DIMENSION: what it says, part by part; nothing else passes through."""


@dataclass(frozen=True)
class Position:
    """A place in a coordinate system, by the names of its axes: ``{"x": 10.0, "y": 20.0}``.

    An axis left out is one it does not say: a position on the sample without z keeps z where it is.
    A point system (a thermometer's) has no axes, so its one position has none.
    """

    system: str
    """sample, stage, detector:<name>, image:<id>, well:B3, electrode:D5, ..."""
    coordinates: dict[str, float] = field(default_factory=dict)


@dataclass
class PlaceShape:
    """One place of a grid of what is mounted (a well, an electrode): its middle on the sample, and
    how wide it is."""

    grid: str
    """Which grid it is of: well, electrode."""
    name: str
    """Its place: well:stage:B3."""
    x: float
    y: float
    diameter_um: Optional[float] = None
    size_um: Optional[float] = None


@dataclass
class HolderShape:
    """What is mounted, in sample micrometres from its top left corner: for a view to draw."""

    name: str
    kind: str
    """slide, dish, plate, mea."""
    width_um: float
    height_um: float
    places: list[PlaceShape] = field(default_factory=list)


@dataclass
class SampleSpace:
    """One sample, on a stage of its own: where what it is mounted on sits, and what that is."""

    sample: str
    """The cube holding it; its hub is ``sample:<cube>``, its stage ``stage:<cube>``."""
    mount: AffineMatrix = field(default_factory=lambda: [list(row) for row in IDENTITY])
    """Stage micrometres to sample micrometres: where what is mounted sits."""
    mount_id: str = "0"
    """Which mounting this is: a new one is a new sample, whose images are its own."""
    mounted_at: str = ""
    """When it was mounted, as ISO 8601: the start of its clock, on which every record of it is."""
    holder: Optional[str] = None
    """What is mounted, by the name the description gives it; None: the sample's frame is its stage's."""
    holders: list[str] = field(default_factory=list)
    """What can be mounted."""
    shape: Optional[HolderShape] = None
    """What is mounted, for a view to draw."""


@dataclass
class DetectorPlacement:
    """Where an imaging detector's pixels are on its sample now: column, row and plane to micrometres."""

    detector: str
    to_sample: AffineMatrix
    """Pixel x (column), y (row) and z to sample micrometres; the image's middle is where it looks."""
    pixel_um: list[float] = field(default_factory=lambda: [0.0, 0.0])
    """How far apart on the sample two neighbouring pixels are, along x and along y."""
    calibrated: bool = False
    """Whether its pixel scale was measured, rather than predicted from the optics."""
    sample: str = ""
    """The sample it sees: what `to_sample` goes to."""


@dataclass
class MeasuredPoint:
    """Where a detector that measures at one point (a thermometer) measures, in its sample's
    micrometres."""

    detector: str
    x: float
    y: float
    z: float
    sample: str = ""
    """The sample it sits beside."""
