"""The expanse state: the frames and images of the current session."""

from dataclasses import dataclass, field

from newswitch.models.frames import Frame, Image


@dataclass
class ExpanseState:
    """Shared state for stage position."""

    current_id: str = field(default_factory=lambda: "expanse_001")
    current_images: list[Image] = field(default_factory=lambda: [])
    current_frames: list[Frame] = field(default_factory=lambda: [])
