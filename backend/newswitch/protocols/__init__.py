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
from .frame_sink import FrameSink
from .hook_manager import HookContext, HookHandler, HookManager, UnsupportedHook
from .io import IOManager
from .metadata import MetadataManager
from .optics import OpticsManager
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
    "FrameSink",
    "HookContext",
    "HookHandler",
    "HookManager",
    "IOManager",
    "OpticsManager",
    "Manager",
    "MetadataManager",
    "UC2BusManager",
    "UnsupportedHook",
]
