"""
Virtual Objective Manager

A virtual objective lens manager for microscopy simulation.
Handles objective switching with magnification and binning simulation.
"""

from dataclasses import dataclass, field
from typing import Optional, List

from newswitch.protocols.objective import ObjectiveState, ObjectiveLens


@dataclass
class ObjectiveConfig:
    """Configuration for the virtual objective manager."""

    objectives: List[ObjectiveLens] = field(
        default_factory=lambda: [
            ObjectiveLens(
                slot=1,
                name="10x Air",
                magnification=10.0,
                numerical_aperture=0.3,
                working_distance=10.0,
                binning_factor=1,
            ),
            ObjectiveLens(
                slot=2,
                name="20x Air",
                magnification=20.0,
                numerical_aperture=0.5,
                working_distance=2.0,
                binning_factor=2,
            ),
            ObjectiveLens(
                slot=3,
                name="40x Water",
                magnification=40.0,
                numerical_aperture=1.0,
                working_distance=0.3,
                binning_factor=2,
            ),
            ObjectiveLens(
                slot=4,
                name="60x Oil",
                magnification=60.0,
                numerical_aperture=1.4,
                working_distance=0.15,
                binning_factor=4,
            ),
        ]
    )
    default_slot: int = 1


class VirtualObjectiveManager:
    """
    A virtual objective manager for microscopy simulation.

    Provides objective switching with magnification and binning simulation.
    Implements the ObjectiveManager protocol.
    """

    def __init__(
        self,
        objective_state: ObjectiveState,
        config: Optional[ObjectiveConfig] = None,
    ) -> None:
        """
        Initialize the virtual objective manager.

        Args:
            objective_state: Shared state for objective.
            config: Objective configuration. Uses defaults if not provided.
        """
        self.objective_state = objective_state
        self.config = config or ObjectiveConfig()

        # Initialize objectives from config
        self.objective_state.mounted_lenses = self.config.objectives
        self._set_objective(self.config.default_slot)

    def _set_objective(self, slot: int) -> ObjectiveLens:
        """Internal method to set the current objective."""
        if slot not in [obj.slot for obj in self.objective_state.mounted_lenses]:
            raise ValueError(f"Unknown objective slot: {slot}")

        obj = next(obj for obj in self.objective_state.mounted_lenses if obj.slot == slot)

        # Update shared state
        self.objective_state.slot = obj.slot
        self.objective_state.magnification = obj.magnification
        self.objective_state.name = obj.name

        return obj

    def switch_objective(self, slot: int) -> None:
        """
        Switch to a specific objective slot (protocol method).

        Args:
            slot: The slot number to move to.

        Returns:
            Dict with the new objective info.
        """
        self._set_objective(slot)

    def toggle_objective(self) -> None:
        """
        Toggle between objectives (cycle through slots) (protocol method).

        Returns:
            Dict with the new objective info.
        """
        slots = [obj.slot for obj in self.objective_state.mounted_lenses]
        current_idx = slots.index(self.objective_state.slot)
        next_idx = (current_idx + 1) % len(slots)
        next_slot = slots[next_idx]

        return self.switch_objective(next_slot)

    def background(self) -> None:
        """Background task for the virtual detector manager."""
        # For this simple implementation, we don't need a background loop
        # since all operations are synchronous and triggered by registered functions.
        pass
