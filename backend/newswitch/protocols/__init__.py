"""
Virtual Microscope Protocols

Protocol definitions for microscope control managers.
Each protocol defines the interface that a manager must implement,
along with the associated state class.
"""

from .stage import StageManager, StageState
from .illumination import IlluminationManager, IlluminationState
from .detector import DetectorManager, CameraState
from .objective import ObjectiveManager, ObjectiveState
from .filter_bank import FilterBankManager, FilterBankState, Filter
from .io import IOManager, IOState, FileHandle, FileFormat
from .light_path import LightPathManager, LightPathState
from .uc2 import (
    UC2BusManager,
    UC2State,
    UC2Event,
    PositionUpdate,
    MotionDone,
    HomingChanged,
    EStopChanged,
    ButtonPressed,
    NodeSeen,
    BusError,
)
from .hook_manager import (
    HookManager,
    Hook,
    HookContext,
    SoftwareAutofocusHook,
    ZCalibrationHook,
    RegisteredHook,
    HookState,
)
from .expanse import ExpanseManager, ExpanseState, Image
from .core import LightPath, Metadata
from .metadata import MetadataManager
from .calibration import CalibrationManager, CalibrationState
from .acquistion_manager import AcquistionManager
from .cache import CacheManager

__all__ = [
    # Managers
    "AcquistionManager",
    # Cache
    "CacheManager",
    # Stage
    "LightPath",
    "Metadata",
    "StageManager",
    "StageState",
    "SoftwareAutofocusHook",
    "CalibrationManager",
    "CalibrationState",
    "ZCalibrationHook",
    "RegisteredHook",
    "HookState",
    # Illumination
    "IlluminationManager",
    "IlluminationState",
    # Light Path
    "LightPathManager",
    "LightPathState",
    # Metadata
    # Hook Manager
    "HookManager",
    "Hook",
    "HookContext",
    # Detector
    "DetectorManager",
    "CameraState",
    "ExpanseManager",
    "ExpanseState",
    "Image",
    # Objective
    "ObjectiveManager",
    "ObjectiveState",
    "MetadataManager",
    # Filter Bank
    "FilterBankManager",
    "FilterBankState",
    "Filter",
    # IO
    "IOManager",
    "IOState",
    "FileHandle",
    "FileFormat",
    # UC2 hardware bus
    "UC2BusManager",
    "UC2State",
    "UC2Event",
    "PositionUpdate",
    "MotionDone",
    "HomingChanged",
    "EStopChanged",
    "ButtonPressed",
    "NodeSeen",
    "BusError",
]
