"""UC2 filter bank manager: FilterBankManager protocol over the UC2 bus.

Realizes the filter wheel as a rotation axis (default "A") driven to
calibrated per-slot positions — the common openUC2 construction. Transport
(CANopen node vs serial JSON) is hidden behind the UC2 bus.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from koil import unkoil
from rekuest_next import model

from newswitch.protocols.filter_bank import Filter, FilterBankState
from newswitch.protocols.uc2 import UC2BusManager


@model
@dataclass
class UC2FilterBankConfig:
    """Configuration for the UC2 filter bank manager."""

    filters: List[Filter] = field(
        default_factory=lambda: [
            Filter(slot=1, name="Open", center_wavelength=0.0, bandwidth=0.0),
            Filter(slot=2, name="GFP 525/50", center_wavelength=525.0, bandwidth=50.0),
            Filter(slot=3, name="RFP 605/70", center_wavelength=605.0, bandwidth=70.0),
        ]
    )
    # Rotation axis carrying the wheel and its per-slot positions
    # (degrees for "A"; micrometers for linear sliders). Index 0 = slot 1.
    axis: str = "A"
    slot_positions: List[float] = field(default_factory=lambda: [0.0, 120.0, 240.0])


class UC2FilterBankManager:
    """Filter bank manager driving an openUC2 filter wheel via the UC2 bus."""

    def __init__(
        self,
        filter_bank_state: FilterBankState,
        bus: UC2BusManager,
        config: Optional[UC2FilterBankConfig] = None,
    ) -> None:
        """Initialize with shared filter state and a connected UC2 bus."""
        self.filter_bank_state = filter_bank_state
        self.bus = bus
        self.config = config or UC2FilterBankConfig()
        self.filter_bank_state.filters = list(self.config.filters)
        self._mark_active(self.filter_bank_state.current_slot or 1)

    def _mark_active(self, slot: int) -> None:
        """Mirror the active slot into the shared state."""
        self.filter_bank_state.current_slot = slot
        for filt in self.filter_bank_state.filters:
            filt.is_active = filt.slot == slot

    def _position_for_slot(self, slot: int) -> float:
        """Return the calibrated wheel position for a slot (1-based)."""
        positions = self.config.slot_positions
        if not 1 <= slot <= len(positions):
            raise ValueError(f"Filter slot {slot} out of range 1..{len(positions)}")
        return positions[slot - 1]

    def switch_filter(self, slot: int) -> Filter:
        """Switch to a specific filter slot (protocol method)."""
        unkoil(self.bus.amove_axis, self.config.axis, self._position_for_slot(slot), True)
        self._mark_active(slot)
        return self.filter_bank_state.get_active_filter()

    def toggle_filter(self) -> Filter:
        """Toggle to the next filter in the wheel (protocol method)."""
        slots = sorted(filt.slot for filt in self.filter_bank_state.filters)
        if not slots:
            raise ValueError("No filters configured")
        current = self.filter_bank_state.current_slot
        current_index = slots.index(current) if current in slots else -1
        return self.switch_filter(slots[(current_index + 1) % len(slots)])

    def get_active_filter(self) -> Optional[Filter]:
        """Return the currently active filter, if any (protocol method)."""
        try:
            return self.filter_bank_state.get_active_filter()
        except ValueError:
            return None

    def get_transmission_at_wavelength(self, wavelength: float) -> float:
        """Approximate the active filter's transmission at a wavelength (protocol method)."""
        active = self.get_active_filter()
        if active is None or active.center_wavelength <= 0.0 or active.bandwidth <= 0.0:
            return 1.0  # open position / no filtering
        half_width = active.bandwidth / 2.0
        if abs(wavelength - active.center_wavelength) <= half_width:
            return active.transmission
        return 0.0
