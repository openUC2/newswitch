"""The objectives: switching between them."""

from newswitch.protocols import (
    ObjectiveManager,
)
from newswitch.states.objective import ObjectiveState


def switch_objective(objective: ObjectiveManager, state: ObjectiveState, slot: int) -> None:
    """
    Switch to a specific objective slot.

    Args:
        slot: Objective slot number
    """
    objective.switch_objective(slot)


def toggle_objective(objective: ObjectiveManager, state: ObjectiveState) -> None:
    """Toggle to the next objective in the turret."""
    objective.toggle_objective()
