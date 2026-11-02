"""The space state: the coordinate graph as it holds now, a hub for each sample."""

from dataclasses import dataclass, field

from newswitch.models.space import (
    CoordinateSystem,
    DetectorPlacement,
    MeasuredPoint,
    SampleSpace,
    Transformation,
)


@dataclass
class SpaceState:
    """The graph, each sample's mount, and every detector placed on its sample."""

    systems: list[CoordinateSystem] = field(default_factory=list)
    """Every coordinate system but the images', with its axes."""
    transformations: list[Transformation] = field(default_factory=list)
    """The edges between them as mikro has them; an image's is in its frame's metadata."""
    samples: dict[str, SampleSpace] = field(default_factory=dict)
    """Each sample by the cube holding it: its mount, and what it is mounted on."""
    detectors: dict[str, DetectorPlacement] = field(default_factory=dict)
    """Where each imaging detector's pixels are on its sample, as a 4x4 for a view to draw."""
    points: dict[str, MeasuredPoint] = field(default_factory=dict)
    """Where each detector that measures at one point (a thermometer) measures, on its sample."""
