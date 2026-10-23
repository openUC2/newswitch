"""
Virtual LED/Illumination Manager

A virtual illumination manager for microscopy simulation.
Supports multiple channels with independent intensity and wavelength control.
"""

from dataclasses import dataclass, field
from typing import List, Optional

from newswitch.models.devices import Illumination
from newswitch.states.illumination import IlluminationState


@dataclass
class LEDConfig:
    """Configuration for the virtual LED manager."""

    sources: List[Illumination] = field(
        default_factory=lambda: [
            Illumination(
                slot=1,
                intensity=80.0,
                wavelength=488.0,
                max_intensity=100.0,
                is_active=True,
            ),
            Illumination(
                slot=2,
                intensity=0.0,
                wavelength=561.0,
                max_intensity=100.0,
                is_active=False,
            ),
            Illumination(
                slot=3,
                intensity=0.0,
                wavelength=640.0,
                max_intensity=100.0,
                is_active=False,
            ),
        ]
    )


class VirtualLEDManager:
    """
    A virtual LED/illumination manager for microscopy simulation.

    Provides multi-channel intensity control with wavelength settings.
    Implements the IlluminationManager protocol.
    """

    def __init__(
        self,
        illumination_state: IlluminationState,
        config: Optional[LEDConfig] = None,
    ) -> None:
        """
        Initialize the virtual LED manager.

        Args:
            illumination_state: Shared state for illumination parameters.
            config: LED configuration. Uses defaults if not provided.
        """
        self.illumination_state = illumination_state
        self.config = config or LEDConfig()

        # Initialize illuminations in state
        self.illumination_state.illuminations = list(self.config.sources)

    def _get_illumination(self, channel: int) -> Optional[Illumination]:
        """Get an illumination source by channel/slot number."""
        for src in self.illumination_state.illuminations:
            if src.slot == channel:
                return src
        return None

    def set_intensity(self, intensity: float, channel: int = 1) -> float:
        """
        Set illumination intensity for a specific channel.

        Args:
            intensity: Intensity value (0 to max_intensity)
            channel: Channel ID (1-indexed by default)

        Returns:
            The clamped intensity value.
        """
        source = self._get_illumination(channel)
        if source is None:
            raise ValueError(f"Unknown channel: {channel}")

        if not source.is_active:
            raise ValueError(
                f"Channel {channel} is not currently active. Please turn it on before setting intensity."
            )

        clamped_intensity = max(source.min_intensity, min(intensity, source.max_intensity))
        source.intensity = clamped_intensity
        return clamped_intensity

    def turn_on(self, channel: int = 1, intensity: Optional[float] = None) -> str:
        """
        Turn on a specific illumination channel.

        Args:
            channel: Channel ID (1-indexed by default)
            intensity: Optional intensity to set. Uses current if not provided.

        Returns:
            Confirmation message.
        """
        source = self._get_illumination(channel)
        if source is None:
            raise ValueError(f"Unknown channel: {channel}")

        source.is_active = True
        if intensity is not None:
            clamped_intensity = max(source.min_intensity, min(intensity, source.max_intensity))
            source.intensity = clamped_intensity

        return f"Channel {channel} turned on at intensity {source.intensity}."

    def turn_off_channel(self, channel: int) -> str:
        """
        Turn off a specific illumination channel.

        Args:
            channel: Channel ID to turn off

        Returns:
            Confirmation message.
        """
        source = self._get_illumination(channel)
        if source is None:
            raise ValueError(f"Unknown channel: {channel}")

        source.is_active = False
        return f"Channel {channel} turned off."

    def background(self) -> None:
        """Background task for the virtual detector manager."""
        # For this simple implementation, we don't need a background loop
        # since all operations are synchronous and triggered by registered functions.
        pass
