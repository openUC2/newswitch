"""Registered functions for the filter wheel. Importing this module registers them."""

from rekuest_next.register import register

from newswitch import protocols
from newswitch.protocols import FilterBankManager, FilterBankState


@register
def switch_filter(
    filter_bank: FilterBankManager, state: FilterBankState, slot: int
) -> protocols.Filter:
    """
    Switch to a specific filter slot.

    Args:
        slot: Filter slot number

    Returns:
        The newly active filter.
    """
    return filter_bank.switch_filter(slot)


@register
def toggle_filter(filter_bank: FilterBankManager, state: FilterBankState) -> protocols.Filter:
    """Toggle to the next filter in the wheel.

    Returns:
        The newly active filter.
    """
    return filter_bank.toggle_filter()
