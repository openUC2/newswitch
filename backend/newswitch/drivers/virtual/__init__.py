"""
Virtual Microscope Managers

A collection of self-contained virtual device managers for microscopy simulation.
Each manager is designed to be independently embeddable into a FastAPI-based
microscope control system.
"""

from .virtual_detector import DetectorConfig, VirtualDetectorManager
from .virtual_filter_bank import FilterBankConfig, VirtualFilterBankManager
from .virtual_led import LEDConfig, VirtualLEDManager
from .virtual_objective import (
    ObjectiveConfig,
    ObjectiveLens,
    VirtualObjectiveManager,
)
from .virtual_stage import StageConfig, VirtualStageManager

__all__ = [
    # Stage
    "VirtualStageManager",
    "StageConfig",
    # LED
    "VirtualLEDManager",
    "LEDConfig",
    # Detector
    "VirtualDetectorManager",
    "DetectorConfig",
    # Objective
    "VirtualObjectiveManager",
    "ObjectiveConfig",
    "ObjectiveLens",
    # Filter Bank
    "VirtualFilterBankManager",
    "FilterBankConfig",
]
