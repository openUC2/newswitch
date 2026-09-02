"""UC2 objective manager: ObjectiveManager protocol over the UC2 bus.

REST transport uses the firmware's native objective slider module
(``/objective_act``); CANopen realizes the changer as a motor node driving
between calibrated slot positions. Both are hidden behind
``UC2BusManager.aobjective_*``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from koil import unkoil
from rekuest_next import model

from newswitch.protocols.objective import ObjectiveLens, ObjectiveState
from newswitch.protocols.uc2 import UC2BusManager


@model
@dataclass
class UC2ObjectiveConfig:
    """Configuration for the UC2 objective manager."""

    lenses: List[ObjectiveLens] = field(
        default_factory=lambda: [
            ObjectiveLens(
                slot=1,
                name="10x Air",
                magnification=10.0,
                numerical_aperture=0.3,
                working_distance=10.0,
            ),
            ObjectiveLens(
                slot=2,
                name="20x Air",
                magnification=20.0,
                numerical_aperture=0.5,
                working_distance=2.0,
            ),
        ]
    )
    home_on_start: bool = False


class UC2ObjectiveManager:
    """Objective manager driving the openUC2 objective changer via the UC2 bus."""

    def __init__(
        self,
        objective_state: ObjectiveState,
        bus: UC2BusManager,
        config: Optional[UC2ObjectiveConfig] = None,
    ) -> None:
        """Initialize with shared objective state and a connected UC2 bus."""
        self.objective_state = objective_state
        self.bus = bus
        self.config = config or UC2ObjectiveConfig()
        self.objective_state.mounted_lenses = list(self.config.lenses)
        self._apply_slot(self.objective_state.slot or 1)

    def _apply_slot(self, slot: int) -> None:
        """Mirror a slot change into the shared state."""
        self.objective_state.slot = slot
        try:
            lens = self.objective_state.get_objective_by_slot(slot)
        except ValueError:
            return
        self.objective_state.magnification = lens.magnification
        self.objective_state.name = lens.name

    def switch_objective(self, slot: int) -> None:
        """Switch to a specific objective slot (protocol method)."""
        slots = [lens.slot for lens in self.objective_state.mounted_lenses]
        if slot not in slots:
            raise ValueError(f"Objective slot {slot} not configured (have {slots})")
        unkoil(self.bus.aobjective_move, slot)
        self._apply_slot(slot)

    def toggle_objective(self) -> None:
        """Toggle to the next mounted objective (protocol method)."""
        slots = sorted(lens.slot for lens in self.objective_state.mounted_lenses)
        if not slots:
            raise ValueError("No objectives configured")
        current_index = (
            slots.index(self.objective_state.slot) if self.objective_state.slot in slots else -1
        )
        self.switch_objective(slots[(current_index + 1) % len(slots)])

    def home(self) -> None:
        """Home the objective changer and reset to slot 1."""
        unkoil(self.bus.aobjective_home)
        self._apply_slot(1)
