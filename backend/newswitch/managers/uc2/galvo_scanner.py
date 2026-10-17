"""UC2 galvo scanner manager driving the galvo through the UC2 bus.

Works over both transports: CANopen uses the command-word doorbell protocol
(OD 0x2600–0x260F; stop is its own nonzero code, never 0), serial uses
``/galvo_act``. Positions are DAC counts (0..4095 for the 12-bit MCP4822).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from koil import unkoil
from rekuest_next import model

from newswitch.protocols.uc2 import UC2BusManager


@model
@dataclass
class UC2GalvoConfig:
    """Configuration for the UC2 galvo scanner."""

    dac_min: int = 0
    dac_max: int = 4095
    default_dwell_us: int = 1
    default_trigger_mode: int = 1  # per-pixel camera trigger


class UC2GalvoScanner:
    """Galvo scanner manager over the transport-agnostic UC2 bus."""

    def __init__(self, bus: UC2BusManager, config: Optional[UC2GalvoConfig] = None) -> None:
        """Initialize with a connected UC2 bus."""
        self.bus = bus
        self.config = config or UC2GalvoConfig()

    def _clamp(self, value: int) -> int:
        """Clamp a DAC value into the configured range."""
        return max(self.config.dac_min, min(self.config.dac_max, int(value)))

    def set_position(self, x: int, y: int) -> None:
        """Move the galvo mirror to an absolute XY position (DAC counts)."""
        unkoil(self.bus.agalvo_goto, self._clamp(x), self._clamp(y))

    def raster_scan(
        self,
        x_min: int = 500,
        x_max: int = 3500,
        y_min: int = 500,
        y_max: int = 3500,
        nx: int = 256,
        ny: int = 256,
        pixel_dwell_us: Optional[int] = None,
        trigger_mode: Optional[int] = None,
        bidirectional: bool = False,
    ) -> None:
        """Configure and start a raster scan."""
        unkoil(
            self.bus.agalvo_raster,
            self._clamp(x_min),
            self._clamp(x_max),
            self._clamp(y_min),
            self._clamp(y_max),
            nx,
            ny,
            pixel_dwell_us or self.config.default_dwell_us,
            trigger_mode if trigger_mode is not None else self.config.default_trigger_mode,
            bidirectional,
        )

    def stop(self) -> None:
        """Stop any active scan."""
        unkoil(self.bus.agalvo_stop)

    def get_status(self) -> dict[str, Any]:
        """Read decoded galvo status flags."""
        return unkoil(self.bus.agalvo_status)
