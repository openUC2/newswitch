"""Registered functions for the expanse (the collected images). Importing this module registers them."""

from rekuest_next.register import register

from newswitch import protocols


@register
def clear_expanse(expanse_manager: protocols.ExpanseManager) -> None:
    """Clear the expanse state, removing all current images."""
    expanse_manager.reset_expanse()
