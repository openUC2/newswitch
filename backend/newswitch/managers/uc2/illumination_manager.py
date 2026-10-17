"""UC2 illumination manager: IlluminationManager protocol over a UC2 bus.

Maps the abstract intensity scale of ``IlluminationState`` onto raw hardware
PWM counts and drives laser/LED channels through the transport-agnostic UC2
bus (CANopen or serial).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from koil import unkoil
from rekuest_next import model

from newswitch.protocols.illumination import Illumination, IlluminationState
from newswitch.protocols.uc2 import UC2BusManager


@model
@dataclass
class UC2IlluminationConfig:
    """Configuration for the UC2 illumination manager."""

    pwm_max: int = 1023  # full-scale hardware PWM (depends on firmware resolution)
    sources: List[Illumination] = field(
        default_factory=lambda: [
            Illumination(slot=1, channel=1, intensity=0.0, max_intensity=100.0),
            Illumination(slot=2, channel=2, intensity=0.0, max_intensity=100.0),
            Illumination(slot=3, channel=3, intensity=0.0, max_intensity=100.0),
        ]
    )


class UC2IlluminationManager:
    """Illumination manager driving openUC2 laser/LED channels via the UC2 bus."""

    def __init__(
        self,
        illumination_state: IlluminationState,
        bus: UC2BusManager,
        config: Optional[UC2IlluminationConfig] = None,
    ) -> None:
        """Initialize with shared illumination state and a connected UC2 bus."""
        self.illumination_state = illumination_state
        self.bus = bus
        self.config = config or UC2IlluminationConfig()
        self.illumination_state.illuminations = list(self.config.sources)

    def _get_illumination(self, channel: int) -> Optional[Illumination]:
        """Find the illumination source configured for a channel."""
        for source in self.illumination_state.illuminations:
            if source.channel == channel or source.slot == channel:
                return source
        return None

    def _to_pwm(self, source: Illumination, intensity: float) -> int:
        """Scale an abstract intensity to raw hardware PWM counts."""
        span = max(source.max_intensity - source.min_intensity, 1e-9)
        fraction = (intensity - source.min_intensity) / span
        return int(round(max(0.0, min(1.0, fraction)) * self.config.pwm_max))

    def set_intensity(self, intensity: float, channel: int = 1) -> float:
        """Set illumination intensity for a channel (protocol method)."""
        source = self._get_illumination(channel)
        if source is None:
            raise ValueError(f"No illumination configured for channel {channel}")
        intensity = max(source.min_intensity, min(source.max_intensity, intensity))
        unkoil(self.bus.aset_laser, channel, self._to_pwm(source, intensity))
        source.intensity = intensity
        source.is_active = intensity > source.min_intensity
        return intensity

    def turn_on(self, channel: int = 1, intensity: Optional[float] = None) -> str:
        """Turn on a channel at the given (or last) intensity (protocol method)."""
        source = self._get_illumination(channel)
        if source is None:
            raise ValueError(f"No illumination configured for channel {channel}")
        value = intensity if intensity is not None else (source.intensity or source.max_intensity)
        applied = self.set_intensity(value, channel=channel)
        return f"Channel {channel} on at {applied}"

    def turn_off_channel(self, channel: int) -> str:
        """Turn off a channel (protocol method)."""
        source = self._get_illumination(channel)
        if source is None:
            raise ValueError(f"No illumination configured for channel {channel}")
        unkoil(self.bus.aset_laser, channel, 0)
        source.is_active = False
        source.intensity = source.min_intensity
        return f"Channel {channel} off"

    # -- LED matrix convenience (not part of the protocol yet) -------------------

    def led_fill(self, r: int, g: int, b: int) -> None:
        """Fill the LED matrix with a uniform colour."""
        unkoil(self.bus.aled_fill, r, g, b)

    def led_off(self) -> None:
        """Turn the LED matrix off."""
        unkoil(self.bus.aled_off)
