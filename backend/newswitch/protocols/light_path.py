"""
Stage Manager Protocol

Defines the protocol for stage/positioner control and associated state.
"""

from typing import Protocol, runtime_checkable

from newswitch.models.light_path import LightPath
from newswitch.protocols.base import Manager
from newswitch.states.light_path import LightPathState


@runtime_checkable
class LightPathManager(Manager, Protocol):
    """Protocol defining the interface for light path managers."""

    state: LightPathState

    def get_light_path_for_detector(self, detector_slot: int) -> LightPath:
        """Get the general light path for a specific detector slot."""
        ...

    def calculate_possible_light_paths(self) -> list[LightPath]:
        """Calculate possible light paths based on the current microscope configuration."""
        ...
