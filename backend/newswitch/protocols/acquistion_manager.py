"""
Stage Manager Protocol

Defines the protocol for stage/positioner control and associated state.
"""

from typing import Protocol, runtime_checkable
from rekuest_next.agents.context import context
from newswitch.protocols.base import Manager
from newswitch.protocols.core import Frame


@context(locks=["expanse_state", "io"])
@runtime_checkable
class AcquistionManager(Manager, Protocol):
    """Protocol defining the interface for expanse managers."""

    def acquire(self, save_to_disk: bool = False) -> list[Frame]:
        """Acquire frames based on the current state of the detector and illumination.

        Args:
            save_to_disk: Also write each detector's snapshot to disk.
        """
        ...
