"""The filter bank state: the mounted filters and the one in the light path."""

from dataclasses import dataclass, field

from newswitch.models.devices import Filter


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
