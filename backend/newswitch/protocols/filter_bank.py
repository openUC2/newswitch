"""
Filter Bank Manager Protocol

Defines the protocol for filter bank control and associated state.
Filters affect how light at different wavelengths passes through to the detector.
"""

from typing import Protocol, runtime_checkable, Optional
from dataclasses import dataclass, field
from newswitch.protocols.base import Manager
from newswitch.arkitekt_app import nsapp


@nsapp.model
@dataclass
class Filter:
    """Configuration for a single optical filter.

    Attributes:
        slot: Filter wheel slot number.
        name: Human-readable filter name.
        center_wavelength: Center wavelength of the filter passband (nm).
        bandwidth: Full width at half maximum of the passband (nm).
        transmission: Peak transmission efficiency (0.0 to 1.0).
        is_active: Whether this filter is currently in the light path.
    """

    slot: int = 1
    name: str = "Empty"
    center_wavelength: float = 0.0  # nm - 0 means no filtering (open)
    bandwidth: float = 0.0  # nm - FWHM
    transmission: float = 1.0  # 0.0 to 1.0
    is_active: bool = False


@nsapp.state(required_locks=["filter_bank"])
@dataclass
class FilterBankState:
    """Shared state for filter bank parameters.

    Attributes:
        filters: List of available filters in the filter wheel.
        current_slot: The currently active filter slot.
    """

    filters: list[Filter] = field(default_factory=lambda: [])
    current_slot: int = 1

    def get_active_filter(self) -> Filter:
        """Get the currently active filter based on the current slot."""
        for filter in self.filters:
            if filter.slot == self.current_slot:
                return filter
        raise ValueError(f"No filter found for slot {self.current_slot}")


@nsapp.context(locks=["filter_bank"])
@runtime_checkable
class FilterBankManager(Manager, Protocol):
    """Protocol defining the interface for filter bank managers."""

    def switch_filter(self, slot: int) -> Filter:
        """Switch to a specific filter by slot number.

        Args:
            slot: Filter slot number to switch to.

        Returns:
            The newly active filter.
        """
        ...

    def toggle_filter(self) -> Filter:
        """Toggle to the next filter in the wheel.

        Returns:
            The newly active filter.
        """
        ...

    def get_active_filter(self) -> Optional[Filter]:
        """Get the currently active filter.

        Returns:
            The active filter, or None if no filter is active.
        """
        ...

    def get_transmission_at_wavelength(self, wavelength: float) -> float:
        """Calculate the transmission factor for a given wavelength.

        Uses the active filter's properties to determine how much light
        at the specified wavelength will pass through.

        Args:
            wavelength: Wavelength in nm.

        Returns:
            Transmission factor (0.0 to 1.0).
        """
        ...
