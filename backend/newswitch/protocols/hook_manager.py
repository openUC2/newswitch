"""
Detector Manager Protocol

Defines the protocol for detector/camera control and associated state.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, Type, runtime_checkable


from newswitch.protocols.stage import StageManager
from newswitch.protocols.base import Manager

from .detector import DetectorManager
from .illumination import IlluminationManager
from .io import IOManager
from .objective import ObjectiveManager
from newswitch.arkitekt_app import nsapp

if TYPE_CHECKING:
    pass


@nsapp.model
class SoftwareAutofocusHook:
    """Data class representing a software autofocus hook to be executed during acquisition."""

    speed: float = 1.0  # Speed of autofocus movement (arbitrary units)


@nsapp.model
class ZCalibrationHook:
    """Data class representing a z-calibration hook to be executed during acquisition."""

    calibration_points: int = 5  # Number of points to use for z-calibration


Hook = SoftwareAutofocusHook | ZCalibrationHook


@nsapp.model
@dataclass
class RegisteredHook:
    """Data class representing a hook to be executed during acquisition."""

    type: str  # HookType as string for serialization


@nsapp.state(required_locks=["hook_registry"])
class HookState:
    """Shared state for camera parameters.

    Default values are set to produce visible images with default illumination.
    Higher exposure and gain ensure the captured images have sufficient
    brightness after uint16→uint8 conversion for PNG output.
    """

    registered_hooks: list[RegisteredHook] = field(default_factory=lambda: [])


@dataclass
class HookContext:
    """Context provided to hooks for access to managers and services."""

    stage_manager: StageManager
    detector_manager: DetectorManager
    illumination_manager: IlluminationManager
    objective_manager: ObjectiveManager
    io_manager: IOManager


class HookHandler(Protocol):
    """Protocol for hook implementations."""

    def __call__(self, hook: Hook, context: HookContext) -> None:
        """Execute the hook."""
        ...


@nsapp.context(locks=["hook_registry"])
@runtime_checkable
class HookManager(Manager, Protocol):
    """Protocol defining the interface for detector/camera managers."""

    def register_hook(self, hook: Type[Hook], hook_handler: HookHandler) -> None:
        """Register a hook implementation.

        The hook can be an instance or a class. If a class is provided, the
        manager attempts to instantiate it with the HookContext. If that fails,
        it falls back to a no-arg constructor and calls initialize if present.
        """

    def execute(self, hook: Hook) -> None:
        """Execute a single hook if registered."""

    def execute_all(self, hooks: list[Hook]) -> None:
        """Execute a list of hooks in order."""
        ...
