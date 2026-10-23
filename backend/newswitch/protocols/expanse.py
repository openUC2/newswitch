"""The expanse protocol: the frames acquired so far, as the frontend shows them in space."""

from typing import Protocol, runtime_checkable

from newswitch.models.frames import Frame, Image
from newswitch.protocols.base import Manager
from newswitch.states.expanse import ExpanseState


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
