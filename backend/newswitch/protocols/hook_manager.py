"""
Detector Manager Protocol

Defines the protocol for detector/camera control and associated state.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Protocol, Type, runtime_checkable

from newswitch.models.hooks import Hook
from newswitch.protocols.base import Manager
from newswitch.protocols.stage import StageManager

from .detector import DetectorManager
from .illumination import IlluminationManager
from .io import IOManager
from .objective import ObjectiveManager

if TYPE_CHECKING:
    pass


@dataclass
class HookContext:
    """Context provided to hooks for access to managers and services.

    A manager is None when the microscope lacks that device (see `newswitch.microscope.parts`).
    """

    stage_manager: Optional[StageManager]
    detector_manager: Optional[DetectorManager]
    illumination_manager: Optional[IlluminationManager]
    objective_manager: Optional[ObjectiveManager]
    io_manager: IOManager


class UnsupportedHook(Exception):
    """A hook that cannot run here: no handler for it, or not at that point of an acquisition."""


class HookHandler(Protocol):
    """Protocol for hook implementations."""

    def __call__(self, hook: Hook, context: HookContext) -> None:
        """Execute the hook."""
        ...


@runtime_checkable
class HookManager(Manager, Protocol):
    """Runs the hooks an acquisition asks for, with the handlers registered for them."""

    def register_hook(self, hook: Type[Hook], hook_handler: HookHandler) -> None:
        """Register a hook implementation.

        The hook can be an instance or a class. If a class is provided, the
        manager attempts to instantiate it with the HookContext. If that fails,
        it falls back to a no-arg constructor and calls initialize if present.
        """

    def check(self, hooks: list[Hook], level: str) -> None:
        """Refuse hooks that cannot run (at `level`: m, t, p or z), before anything moves."""
        ...

    def execute(self, hook: Hook) -> None:
        """Run one hook; one without a handler is refused (`UnsupportedHook`)."""
        ...

    def execute_all(self, hooks: list[Hook]) -> None:
        """Run hooks in order."""
        ...
