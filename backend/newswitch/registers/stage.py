"""Registered functions for the stage. Importing this module registers them.

Per-axis homing and stopping on the UC2 bus are in `newswitch.registers.uc2`.
"""

from typing import Optional

from rekuest_next.api.schema import OptimisticInput
from rekuest_next.register import register

from newswitch.protocols import StageManager, StageState


# This function uses the optimistic pattern
# It allows for the function to define how the state should be updated optimistically at the moment the function runs
# This is useful for setters like this move function, where we want the UI to reflect the new position immediately,
# without waiting for the function to complete
@register(
    optimistics=[
        OptimisticInput(
            state=StageState.__name__,
            path="",
            accessor="({...state, x: args.x, y: args.y, z: args.z, a: args.a})",
        )
    ],
)
def move_stage(
    stage: StageManager,
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
    stage.move(x=x, y=y, z=z, a=a, step_size=step_size, is_absolute=is_absolute)


@register
def move_home(stage: StageManager, state: StageState) -> None:
    """Move stage to home position."""
    pos = stage.move_home()
    return pos


# TODO: Why was this function defined?


@register
def move_to_stage_position(
    stage: StageManager,
    state: StageState,
    position_x: int,
    position_y: int,
    position_z: int,
) -> None:
    """
    Move the stage to a specified position.

    Args:
        position: Target stage position
    """
    stage.move(
        x=position_x,
        y=position_y,
        z=position_z,
        is_absolute=True,
    )
