"""
newswitch - Virtual Microscope Management System

This package provides:
- managers: Concrete implementations of virtual microscope components
- protocols: Protocol definitions and state classes for dependency injection
"""

from .managers.virtual import (
    VirtualStageManager,
    StageConfig,
    VirtualLEDManager,
    LEDConfig,
    VirtualDetectorManager,
    DetectorConfig,
    VirtualSetup,
    SceneConfig,
    VirtualObjectiveManager,
    ObjectiveConfig,
    ObjectiveLens,
)

from .protocols import (
    StageManager,
    StageState,
    IlluminationManager,
    IlluminationState,
    DetectorManager,
    CameraState,
    ObjectiveManager,
    ObjectiveState,
)

__all__ = [
    # Managers
    "VirtualStageManager",
    "StageConfig",
    "VirtualLEDManager",
    "LEDConfig",
    "VirtualDetectorManager",
    "DetectorConfig",
    "VirtualSetup",
    "SceneConfig",
    "VirtualObjectiveManager",
    "ObjectiveConfig",
    "ObjectiveLens",
    # Protocols
    "StageManager",
    "StageState",
    "IlluminationManager",
    "IlluminationState",
    "DetectorManager",
    "CameraState",
    "ObjectiveManager",
    "ObjectiveState",
]
