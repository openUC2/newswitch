"""Hooks a routine runs at points of an acquisition (autofocus, z calibration)."""

from dataclasses import dataclass


@dataclass
class SoftwareAutofocusHook:
    """Refocus by software: sweep Z around the current position, move to the sharpest plane."""

    z_range: float = 20.0  # total sweep range (um), centred on the current Z
    steps: int = 11  # planes scored in the sweep (>= 3)


@dataclass
class ZCalibrationHook:
    """Data class representing a z-calibration hook to be executed during acquisition."""

    calibration_points: int = 5  # Number of points to use for z-calibration


Hook = SoftwareAutofocusHook | ZCalibrationHook


@dataclass
class RegisteredHook:
    """Data class representing a hook to be executed during acquisition."""

    type: str  # HookType as string for serialization
