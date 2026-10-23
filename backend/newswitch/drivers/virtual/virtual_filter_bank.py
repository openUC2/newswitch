"""
Virtual Filter Bank Manager

A virtual filter bank manager for microscopy simulation.
Handles filter switching with wavelength-dependent transmission profiles.
"""

import math
from dataclasses import dataclass, field
from typing import List, Optional

from newswitch.models.devices import Filter
from newswitch.states.filter_bank import FilterBankState


@dataclass
class FilterBankConfig:
    """Configuration for the virtual filter bank manager."""

    filters: List[Filter] = field(
        default_factory=lambda: [
            Filter(
                slot=1,
                name="DAPI",
                center_wavelength=461.0,
                bandwidth=40.0,
                transmission=0.95,
                is_active=True,  # First filter is active by default
            ),
            Filter(
                slot=2,
                name="GFP",
                center_wavelength=525.0,
                bandwidth=50.0,
                transmission=0.92,
                is_active=False,
            ),
            Filter(
                slot=3,
                name="TRITC",
                center_wavelength=572.0,
                bandwidth=28.0,
                transmission=0.90,
                is_active=False,
            ),
            Filter(
                slot=4,
                name="Cy5",
                center_wavelength=670.0,
                bandwidth=40.0,
                transmission=0.88,
                is_active=False,
            ),
            Filter(
                slot=5,
                name="Open",
                center_wavelength=0.0,  # 0 means no filtering
                bandwidth=0.0,
                transmission=1.0,
                is_active=False,
            ),
        ]
    )
    default_slot: int = 1


class VirtualFilterBankManager:
    """
    A virtual filter bank manager for microscopy simulation.

    Provides filter switching with wavelength-dependent transmission profiles.
    Implements the FilterBankManager protocol.

    The transmission profile uses a Gaussian approximation centered on the
    filter's center wavelength with the bandwidth as FWHM.
    """

    def __init__(
        self,
        filter_bank_state: FilterBankState,
        config: Optional[FilterBankConfig] = None,
    ) -> None:
        """
        Initialize the virtual filter bank manager.

        Args:
            filter_bank_state: Shared state for filter bank parameters.
            config: Filter bank configuration. Uses defaults if not provided.
        """
        self.filter_bank_state = filter_bank_state
        self.config = config or FilterBankConfig()

        # Initialize filters from config
        self.filter_bank_state.filters = list(self.config.filters)

        # Set active filter to default
        self._set_active_filter(self.config.default_slot)

    def _get_filter(self, slot: int) -> Optional[Filter]:
        """Get a filter by its slot number."""
        for f in self.filter_bank_state.filters:
            if f.slot == slot:
                return f
        return None

    def _set_active_filter(self, slot: int) -> Filter:
        """Internal method to set the active filter."""
        target_filter = self._get_filter(slot)
        if target_filter is None:
            raise ValueError(f"No filter found with slot {slot}")

        # Deactivate all filters
        for f in self.filter_bank_state.filters:
            f.is_active = False

        # Activate the target filter
        target_filter.is_active = True
        self.filter_bank_state.current_slot = slot

        return target_filter

    def switch_filter(self, slot: int) -> Filter:
        """
        Switch to a specific filter by slot number.

        Args:
            slot: Filter slot number to switch to.

        Returns:
            The newly active filter.

        Raises:
            ValueError: If the slot number is invalid.
        """
        return self._set_active_filter(slot)

    def toggle_filter(self) -> Filter:
        """
        Toggle to the next filter in the wheel.

        Cycles through available filters in order by slot number.

        Returns:
            The newly active filter.
        """
        slots = sorted([f.slot for f in self.filter_bank_state.filters])
        current_idx = slots.index(self.filter_bank_state.current_slot)
        next_idx = (current_idx + 1) % len(slots)
        next_slot = slots[next_idx]

        return self.switch_filter(next_slot)

    def get_active_filter(self) -> Optional[Filter]:
        """
        Get the currently active filter.

        Returns:
            The active filter, or None if no filter is active.
        """
        for f in self.filter_bank_state.filters:
            if f.is_active:
                return f
        return None

    def get_transmission_at_wavelength(self, wavelength: float) -> float:
        """
        Calculate the transmission factor for a given wavelength.

        Uses a Gaussian approximation of the filter passband.
        For an "Open" filter (center_wavelength=0), returns full transmission.

        Args:
            wavelength: Wavelength in nm.

        Returns:
            Transmission factor (0.0 to 1.0).
        """
        active_filter = self.get_active_filter()
        if active_filter is None:
            return 1.0  # No filter means full transmission

        # Open filter (no filtering)
        if active_filter.center_wavelength == 0.0:
            return active_filter.transmission

        # Calculate Gaussian transmission profile
        # FWHM to sigma conversion: sigma = FWHM / (2 * sqrt(2 * ln(2)))
        if active_filter.bandwidth <= 0:
            # Zero bandwidth means perfect blocking except at center
            if abs(wavelength - active_filter.center_wavelength) < 1.0:
                return active_filter.transmission
            return 0.0

        sigma = active_filter.bandwidth / (2.0 * math.sqrt(2.0 * math.log(2.0)))
        delta = wavelength - active_filter.center_wavelength
        gaussian = math.exp(-(delta**2) / (2.0 * sigma**2))

        return active_filter.transmission * gaussian

    def list_filters(self) -> list[Filter]:
        """
        List all available filters.

        Returns:
            List of all filters in the filter bank.
        """
        return self.filter_bank_state.filters

    def background(self) -> None:
        """Background task for the virtual detector manager."""
        # For this simple implementation, we don't need a background loop
        # since all operations are synchronous and triggered by registered functions.
        pass
