"""The manager protocols: what each part of a microscope (and each service) can do.

Implementations live in `newswitch.drivers` (hardware and simulation) and
`newswitch.services`; the states they publish in `newswitch.states`, the values they
exchange in `newswitch.models`.
"""

from .acquisition import AcquisitionManager
from .base import BackgroundManager, Manager
from .cache import CacheManager
from .calibration import CalibrationManager
from .detector import DetectorFrame, DetectorManager, DetectorSessionInfo
from .expanse import ExpanseManager
from .filter_bank import FilterBankManager
from .hook_manager import HookContext, HookHandler, HookManager, UnsupportedHook
from .illumination import IlluminationManager
from .io import IOManager
from .light_path import LightPathManager
from .metadata import MetadataManager
from .objective import ObjectiveManager
from .stage import StageManager
from .uc2 import UC2BusManager

__all__ = [
    "AcquisitionManager",
    "BackgroundManager",
    "CacheManager",
    "CalibrationManager",
    "DetectorFrame",
    "DetectorManager",
    "DetectorSessionInfo",
    "ExpanseManager",
    "FilterBankManager",
    "HookContext",
    "HookHandler",
    "HookManager",
    "IlluminationManager",
    "IOManager",
    "LightPathManager",
    "Manager",
    "MetadataManager",
    "ObjectiveManager",
    "StageManager",
    "UC2BusManager",
    "UnsupportedHook",
]
