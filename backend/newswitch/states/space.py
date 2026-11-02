"""The space state: where the sample is on the stage, and where every detector's pixels are on it."""

from dataclasses import dataclass, field
from typing import Optional

from newswitch.models.light_path import AffineMatrix
from newswitch.models.space import IDENTITY, DetectorPlacement, HolderShape


@dataclass
class SpaceState:
    """The mount, and every detector placed on the sample; the sample is the hub of the graph."""

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
