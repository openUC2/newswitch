"""
Illumination Manager Protocol

Defines the protocol for illumination/LED control and associated state.
"""

from typing import Optional, Protocol, runtime_checkable

from newswitch.protocols.base import Manager


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
