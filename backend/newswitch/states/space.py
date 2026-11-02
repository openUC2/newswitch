"""The space state: the coordinate graph as it holds now, with the sample as its hub."""

from dataclasses import dataclass, field
from typing import Optional

from newswitch.models.light_path import AffineMatrix
from newswitch.models.space import (
    IDENTITY,
    CoordinateSystem,
    DetectorPlacement,
    HolderShape,
    MeasuredPoint,
    Transformation,
)


@dataclass
class SpaceState:
    """The graph, the mount, and every detector placed on the sample."""

    systems: list[CoordinateSystem] = field(default_factory=list)
    """Every coordinate system but the images', with its axes."""
    transformations: list[Transformation] = field(default_factory=list)
    """The edges between them as mikro has them; an image's is in its frame's metadata."""
    mount: AffineMatrix = field(default_factory=lambda: [list(row) for row in IDENTITY])
    """Stage micrometres to sample micrometres: where what is mounted sits."""
    mount_id: str = "0"
    """Which mounting this is: a new one is a new sample, whose images are its own."""
    holder: Optional[str] = None
    """What is mounted, by the name the description gives it; None: the sample's frame is the stage's."""
    holders: list[str] = field(default_factory=list)
    """What can be mounted."""
    shape: Optional[HolderShape] = None
    """What is mounted, for a view to draw."""
    detectors: dict[str, DetectorPlacement] = field(default_factory=dict)
    """Where each imaging detector's pixels are on the sample, as a 4x4 for a view to draw."""
    points: dict[str, MeasuredPoint] = field(default_factory=dict)
    """Where each detector that measures at one point (a thermometer) measures, on the sample."""
