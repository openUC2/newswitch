"""
Illumination Manager Protocol

Defines the protocol for illumination/LED control and associated state.
"""

from typing import Optional, Protocol, runtime_checkable
from dataclasses import dataclass, field
from newswitch.protocols.base import Manager
from enum import Enum
from arkitekt import model_field
from newswitch.arkitekt_app import nsapp


class IlluminationKind(str, Enum):
    """Enumeration of illumination source kinds."""

    LED = "LED"
    LASER = "LASER"
    HALOGEN = "HALOGEN"


@nsapp.model
class Illumination:
    """Shared state for illumination parameters.

    Note: intensity is divided by 1000 in the detector for actual scaling,
    so 10000.0 gives an effective intensity of 10.0.
    """

    kind: IlluminationKind = model_field(default=IlluminationKind.LED)
    slot: int = 1
    intensity: float = 10000.0
    wavelength: float = 0.0
    fartface: float = 56
    channel: int = 1
    max_intensity: float = 100000.0
    min_intensity: float = 0.0
    is_active: bool = False
    intensity: float = 10000.0


@nsapp.state(required_locks=["illumination"])
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


@nsapp.context(locks=["illumination"])
@runtime_checkable
class IlluminationManager(Manager, Protocol):
    """Protocol defining the interface for illumination managers."""

    def set_intensity(self, intensity: float, channel: int = 1) -> float:
        """Set illumination intensity for a specific channel."""
        ...

    def turn_on(self, channel: int = 1, intensity: Optional[float] = None) -> str:
        """Turn on a specific illumination channel."""
        ...

    def turn_off_channel(self, channel: int) -> str:
        """Turn off a specific illumination channel."""
        ...
