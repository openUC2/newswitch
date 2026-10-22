"""
Stage Manager Protocol

Defines the protocol for stage/positioner control and associated state.
"""

from typing import Optional, Protocol, runtime_checkable, List
from newswitch.protocols.base import Manager
from newswitch.protocols.core import LightPath
from arkitekt import model_field
from newswitch.arkitekt_app import nsapp


@nsapp.state
class LightPathState:
    """State class for the LightPathManager, holding the current light path information."""

    light_paths: List[LightPath] = model_field(default_factory=list)
    current_light_path: Optional[LightPath] = None


@nsapp.context
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
