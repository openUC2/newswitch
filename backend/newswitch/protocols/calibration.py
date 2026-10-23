"""
Illumination Manager Protocol

Defines the protocol for illumination/LED control and associated state.
"""

from typing import Protocol, runtime_checkable

from newswitch.models.calibration import CalibratedLightPath
from newswitch.protocols.base import Manager


@runtime_checkable
class CalibrationManager(Manager, Protocol):
    """Protocol defining the interface for illumination managers."""

    def set_calibrated_state(self, calibrated_light_path: CalibratedLightPath) -> None:
        """Set the calibrated state for a given light path configuration."""
