"""The optics state: what the optics find under the current values."""

from dataclasses import dataclass, field

from newswitch.models.light_path import LightElement
from newswitch.models.optics import DetectorOptics, OpticalChannel, SourceOptics


@dataclass
class OpticsState:
    """Per detector and per source, by the name of its cube; and which channels that makes."""

    detectors: dict[str, DetectorOptics] = field(default_factory=dict)
    sources: dict[str, SourceOptics] = field(default_factory=dict)
    channels: list[OpticalChannel] = field(default_factory=list)
    elements: dict[str, LightElement] = field(default_factory=dict)
    """What is in every cube on the way to a detector now, for a view to read by cube."""
