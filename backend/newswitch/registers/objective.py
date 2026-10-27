"""Registered functions for the objective turret. Importing this module registers them.

Homing the objective changer on the UC2 bus is in `newswitch.registers.uc2`.
"""

from rekuest_next.register import register

from newswitch.protocols import ObjectiveManager, ObjectiveState


@register
def switch_objective(objective: ObjectiveManager, state: ObjectiveState, slot: int) -> None:
    """
    Switch to a specific objective slot.

    Args:
        slot: Objective slot number
    """
    objective.switch_objective(slot)


@register
def toggle_objective(objective: ObjectiveManager, state: ObjectiveState) -> None:
    """Toggle to the next objective in the turret."""
    objective.toggle_objective()
