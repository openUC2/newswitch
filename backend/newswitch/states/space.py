"""The space state: where the sample is on the stage, and where every detector's pixels are on it."""

from dataclasses import dataclass, field

from newswitch.models.light_path import AffineMatrix
from newswitch.models.space import IDENTITY, DetectorPlacement


@dataclass
class SpaceState:
    """The mount, and every detector placed on the sample; the sample is the hub of the graph."""

    mount: AffineMatrix = field(default_factory=lambda: [list(row) for row in IDENTITY])
    """Stage micrometres to sample micrometres: where what is mounted sits."""
    mount_id: str = "0"
    """Which mounting this is: a new one is a new sample, whose images are its own."""
    detectors: dict[str, DetectorPlacement] = field(default_factory=dict)
