"""
Objective Manager Protocol

Defines the protocol for objective lens control and associated state.
"""

from typing import Protocol, runtime_checkable
from dataclasses import dataclass, field

from newswitch.protocols.base import Manager
from newswitch.arkitekt_app import nsapp


@nsapp.model
@dataclass
class ObjectiveLens:
    """Configuration for a single objective lens."""

    slot: int
    name: str
    magnification: float
    numerical_aperture: float
    working_distance: float
    binning_factor: int = 1


@nsapp.state(required_locks=["objective"])
@dataclass
class ObjectiveState:
    """Shared state for objective."""

    slot: int = 1
    magnification: float = 10.0
    name: str = "10x Air"
    mounted_lenses: list[ObjectiveLens] = field(default_factory=lambda: [])

    def get_active_objective(self) -> ObjectiveLens:
        """Get the currently active objective lens based on the current slot."""
        for lens in self.mounted_lenses:
            if lens.slot == self.slot:
                return lens
        raise ValueError(f"No objective lens found for slot {self.slot}")

    def get_objective_by_slot(self, slot: int) -> ObjectiveLens:
        """Get an objective lens by its slot number."""
        for lens in self.mounted_lenses:
            if lens.slot == slot:
                return lens
        raise ValueError(f"No objective lens found for slot {slot}")


@nsapp.context
@runtime_checkable
class ObjectiveManager(Manager, Protocol):
    """Protocol defining the interface for objective managers."""

    def switch_objective(self, slot: int) -> None:
        """Switch to a specific objective slot."""
        ...

    def toggle_objective(self) -> None:
        """Toggle to next objective."""
        ...
