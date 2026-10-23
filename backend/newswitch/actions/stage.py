"""The stage: moving it, homing it."""

from typing import Optional

from arkitekt import Task

from newswitch.protocols import (
    StageManager,
)
from newswitch.states.stage import StageState


# This function uses the optimistic pattern
# It allows for the function to define how the state should be updated optimistically at the moment the function runs
# This is useful for setters like this move function, where we want the UI to reflect the new position immediately,
# without waiting for the function to complete
def move_stage(
    stage: StageManager,
    task: Task,
    x: Optional[float] = None,
    y: Optional[float] = None,
    z: Optional[float] = None,
    a: Optional[float] = None,
    is_absolute: bool = False,
    step_size: float = 1.0,
) -> None:
    """
    Move the stage to a new position.

    Args:
        x: X position (micrometers)
        y: Y position (micrometers)
        z: Z position (micrometers)
        a: A (rotation) position
        is_absolute: If True, move to absolute position; if False, relative move
        step_size: Step size in micrometers for movement simulation (default: 1.0)
    """
    # Read current position from state
    stage.move(x=x, y=y, z=z, a=a, step_size=step_size, is_absolute=is_absolute, task=task)


def move_home(stage: StageManager, state: StageState) -> None:
    """Move stage to home position."""
    pos = stage.move_home()
    return pos
