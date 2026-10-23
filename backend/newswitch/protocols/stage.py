"""
Stage Manager Protocol

Defines the protocol for stage/positioner control and associated state.
"""

from typing import Optional, Protocol, runtime_checkable

from arkitekt import Task

from newswitch.protocols.base import Manager
from newswitch.states.stage import StageState


@runtime_checkable
class StageManager(Manager, Protocol):
    """Protocol defining the interface for stage managers."""

    state: StageState

    def move(
        self,
        x: Optional[float] = None,
        y: Optional[float] = None,
        z: Optional[float] = None,
        a: Optional[float] = None,
        step_size: Optional[float] = None,
        is_absolute: bool = False,
        task: Optional[Task] = None,
    ) -> None:
        """Move the stage to a new position.

        ``task`` is the action's, for progress and pause points while the stage travels.
        """
        ...

    def move_home(self) -> None:
        """Move the stage to the home position."""
        ...
