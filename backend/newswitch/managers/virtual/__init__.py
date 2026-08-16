"""
Virtual Microscope Managers

A collection of self-contained virtual device managers for microscopy simulation.
Each manager is designed to be independently embeddable into a FastAPI-based
microscope control system.
"""

from .virtual_stage import VirtualStageManager, StageConfig
from .virtual_led import VirtualLEDManager, LEDConfig
from .virtual_detector import VirtualDetectorManager, DetectorConfig
from .virtual_setup import VirtualSetup, SceneConfig
from .virtual_objective import (
    VirtualObjectiveManager,
    ObjectiveConfig,
    ObjectiveLens,
)
from .virtual_filter_bank import VirtualFilterBankManager, FilterBankConfig

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
    # Setup (simulated optical scene)
    "VirtualSetup",
    "SceneConfig",
    # Objective
    "VirtualObjectiveManager",
    "ObjectiveConfig",
    "ObjectiveLens",
    # Filter Bank
    "VirtualFilterBankManager",
    "FilterBankConfig",
]
