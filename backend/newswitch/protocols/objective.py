"""
Objective Manager Protocol

Defines the protocol for objective lens control and associated state.
"""

from typing import Protocol, runtime_checkable

from newswitch.protocols.base import Manager


@runtime_checkable
class ObjectiveManager(Manager, Protocol):
    """Protocol defining the interface for objective managers."""

    def switch_objective(self, slot: int) -> None:
        """Switch to a specific objective slot."""
        ...

    def toggle_objective(self) -> None:
        """Toggle to next objective."""
        ...
