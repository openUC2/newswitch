"""The filter bank: switching filters."""

from newswitch import models
from newswitch.protocols import (
    FilterBankManager,
)
from newswitch.states.filter_bank import FilterBankState


def switch_filter(
    filter_bank: FilterBankManager, state: FilterBankState, slot: int
) -> models.Filter:
    """
    Switch to a specific filter slot.

    Args:
        slot: Filter slot number

    Returns:
        The newly active filter.
    """
    return filter_bank.switch_filter(slot)


def toggle_filter(filter_bank: FilterBankManager, state: FilterBankState) -> models.Filter:
    """Toggle to the next filter in the wheel.

    Returns:
        The newly active filter.
    """
    return filter_bank.toggle_filter()
