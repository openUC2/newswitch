"""
Stage Manager Protocol

Defines the protocol for stage/positioner control and associated state. # TODO: What is this?!
"""

from typing import Protocol, runtime_checkable
from dataclasses import field
from rekuest_next.agents.context import context
from rekuest_next import state
from newswitch.protocols.base import Manager
from newswitch.protocols.core import Image, Frame


@state(required_locks=["expanse_state"])
class ExpanseState:
    """Shared state for stage position."""

    current_id: str = field(default_factory=lambda: "expanse_001")
    current_images: list[Image] = field(default_factory=lambda: [])
    current_frames: list[Frame] = field(default_factory=lambda: [])


@context(locks=["expanse_state"])
@runtime_checkable
class ExpanseManager(Manager, Protocol):
    """Protocol defining the interface for expanse managers."""

    state: ExpanseState

    def add_image(self, image: Image) -> None:
        """Add a new image to the current state."""
        ...

    def add_frame(self, frame: Frame) -> None:
        """Add a new frame to the current state."""
        ...

    def reset_expanse(self) -> None:
        """Reset the expanse state, clearing all current images."""
        ...
