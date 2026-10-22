"""
Stage Manager Protocol

Defines the protocol for stage/positioner control and associated state.
"""

from typing import Protocol, runtime_checkable
from newswitch.protocols.base import Manager
from newswitch.protocols.core import LightPath, LightPathState, Metadata
from newswitch.arkitekt_app import nsapp


@nsapp.context
@runtime_checkable
class MetadataManager(Manager, Protocol):
    """Protocol defining the interface for expanse managers."""

    def get_metadata_for_light_path(self, light_path: LightPath) -> Metadata:
        """Get the current metadata, including image IDs and affine matrices."""
        ...

    def get_current_state_for_light_path(self, light_path: LightPath) -> LightPathState:
        """Get the hash of the light path configuration for a given light path."""
        ...
