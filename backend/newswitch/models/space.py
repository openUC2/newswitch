"""Where things are: a place in a coordinate system, and where a detector's pixels are."""

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


@dataclass(frozen=True)
class Position:
    """A place in a coordinate system: the sample, the stage, an image, a well."""

    system: str
    """The sample, the stage, detector:<name>, image:<id>, well:<B3>, ..."""
    x: float
    y: float
    z: Optional[float] = None
    """None: wherever z is."""


@dataclass
class DetectorPlacement:
    """Where a detector's pixels are on the sample now: column, row and plane to micrometres."""

    detector: str
    to_sample: AffineMatrix
    """Pixel x (column), y (row) and z to sample micrometres; the image's middle is where it looks."""
    pixel_um: list[float] = field(default_factory=lambda: [0.0, 0.0])
    """How far apart on the sample two neighbouring pixels are, along x and along y."""
    calibrated: bool = False
    """Whether its pixel scale was measured, rather than predicted from the optics."""
