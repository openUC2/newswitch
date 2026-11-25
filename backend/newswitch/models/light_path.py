"""The light paths of a microscope: its elements and how light connects them, as it describes them."""

from dataclasses import dataclass, field
from typing import Optional

from arkitekt import model_field

#: A 4x4 pose.
AffineMatrix = list[list[float]]


@dataclass
class LightElement:
    """One cube on a light path: what is in place in it, as far as can be shown."""

    name: str
    """The cube's name in the description."""
    kind: str
    """What the element is: source, lens, filter, ... as the description says."""
    label: str
    facts: dict[str, str] = field(default_factory=dict)
    """What it is made of, ready to show, by what each is."""
    values: dict[str, str] = field(default_factory=dict)
    """What its actuators are set to, ready to show, by variable."""


@dataclass
class LightEdge:
    """Light going from one element to the next."""

    source: str
    target: str
    via: Optional[str] = None
    """Which way it leaves a dichroic or a splitter."""
    side: Optional[str] = None
    """How it lands on the sample: epi, transmitted, orthogonal."""


@dataclass
class LightPath:
    """Every way light can take to one detector, as the description's edges say."""

    detector: str
    elements: list[LightElement] = field(default_factory=list)
    edges: list[LightEdge] = field(default_factory=list)


@dataclass
class LightPathSnapshot:
    """A light path as it was for an image, and what that image's calibration depends on."""

    key: str = ""
    """Of what changes where a pixel looks: a calibration holds for as long as this does."""
    hash: str = ""
    """Of everything set on the way, so that two images with the same setup can be told apart."""
    elements: list[LightElement] = field(default_factory=list)
    edges: list[LightEdge] = field(default_factory=list)


@dataclass
class CalibratedLightPath:
    """How a step along a column and along a row moves on the sample, for one light path: as the
    optics predict it, or as it was measured (`newswitch.calibration`)."""

    affine_matrix: AffineMatrix = model_field(
        default_factory=lambda: [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ],
        description="Pixel to sample micrometres, without where it looks: its 2x2 is the scale",
    )
    key: str = model_field(
        default="",
        description="Of what changes where a pixel looks: this matrix holds for as long as it does",
    )
