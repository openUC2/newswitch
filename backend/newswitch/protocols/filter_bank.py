"""
Filter Bank Manager Protocol

Defines the protocol for filter bank control and associated state.
Filters affect how light at different wavelengths passes through to the detector.
"""

from typing import Optional, Protocol, runtime_checkable

from newswitch.models.devices import Filter
from newswitch.protocols.base import Manager


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
