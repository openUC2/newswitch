"""
Stage Manager Protocol

Defines the protocol for stage/positioner control and associated state.
"""

from typing import Protocol, runtime_checkable
from newswitch.protocols.base import Manager
from newswitch.protocols.core import Frame
from newswitch.arkitekt_app import nsapp


@nsapp.context(locks=["expanse_state", "io"])
@runtime_checkable
class AcquistionManager(Manager, Protocol):
    """Protocol defining the interface for expanse managers."""

    def acquire(self) -> list[Frame]:
        """Acquire frames based on the current state of the detector and illumination."""
        ...
