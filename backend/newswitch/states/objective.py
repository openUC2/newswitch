"""The objective state: the mounted lenses and the one in use."""

from dataclasses import dataclass, field

from newswitch.models.devices import ObjectiveLens


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
