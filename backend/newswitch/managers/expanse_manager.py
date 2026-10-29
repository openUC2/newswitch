"""ExpanseManager for managing the state of the current acquisition session, including the images acquired and their associated metadata."""

from __future__ import annotations


import logging
from newswitch.protocols.expanse import ExpanseState, Image, Frame

logger = logging.getLogger(__name__)


class ExpanseManager:
    """Registry and execution for acquisition hooks."""

    def __init__(self, expanse: ExpanseState) -> None:
        """Initialize the ExpanseManager with the provided ExpanseState and an empty registry."""
        self.state = expanse

    def add_image(self, image: Image) -> None:
        """Add an image to the expanse state."""
        self.state.current_images.append(image)

    def add_frame(self, frame: Frame) -> None:
        """Add a new frame to the current state."""
        self.state.current_frames.append(frame)
        logger.debug("%s", self.state)

    def reset_expanse(self) -> None:
        """Reset the expanse state, clearing all current images."""
        self.state.current_images = []
        self.state.current_frames = []
