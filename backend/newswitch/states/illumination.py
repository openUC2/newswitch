"""The illumination state: the light sources and their settings."""

from dataclasses import dataclass, field

from newswitch.models.devices import Illumination


@dataclass
class IlluminationState:
    """Shared state for illumination parameters.

    Note: intensity is divided by 1000 in the detector for actual scaling,
    so 10000.0 gives an effective intensity of 10.0.
    """

    illuminations: list[Illumination] = field(default_factory=lambda: [])

    def get_illumination_by_slot(self, slot: int) -> Illumination:
        """Get the illumination configuration for a specific slot."""
        for illum in self.illuminations:
            if illum.slot == slot:
                return illum
        raise ValueError(f"No illumination found for slot {slot}")
