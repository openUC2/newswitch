"""The core every microscope has: the expanse of the current session."""

from newswitch import protocols


def clear_expanse(expanse_manager: protocols.ExpanseManager) -> None:
    """Clear the expanse state, removing all current images."""
    expanse_manager.reset_expanse()
