"""
Stage Manager Protocol

Defines the protocol for stage/positioner control and associated state.
"""

from typing import Optional, Protocol, runtime_checkable
from dataclasses import field
from newswitch.protocols.base import Manager
from newswitch.arkitekt_app import nsapp


@nsapp.state(required_locks=["z_range"])
class ZRangeState:
    """Shared state for Z focussing"""

    current_z: float = 0.0
    start_z: float = 0.0
    end_z: float = 0.0
    max_z: float = 100.0
    min_z: float = -100.0
    registered_step_sizes: list[float] = field(default_factory=lambda: [0.1, 1.0, 10.0, 100.0])


@nsapp.context(locks=["z_range"])
@runtime_checkable
class ZRangeManager(Manager, Protocol):
    """Protocol defining the interface for Z range managers."""

    state: ZRangeState

    def set_range(
        self,
        start_z: Optional[float] = None,
        end_z: Optional[float] = None,
    ) -> None:
        """Set the Z range for a Z stack acquisition."""
        ...

    def move(
        self,
        z: Optional[float] = None,
    ) -> None:
        """Move the stage to a new position."""
        ...

    def move_home(self) -> None:
        """Move the stage to the home position."""
        ...
