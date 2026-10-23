"""A generic claibration manager"""

from __future__ import annotations

from newswitch.models.calibration import CalibratedLightPath
from newswitch.states.calibration import CalibrationState


class CalibrationManager:
    """Registry and execution for acquisition hooks."""

    def __init__(self, calibration_state: CalibrationState) -> None:
        """Initialize the CalibrationManager with the provided CalibrationState."""
        self.state = calibration_state

    def set_calibrated_state(self, calibrated_light_path: CalibratedLightPath) -> None:
        """Set the calibrated state for a given light path configuration."""
        self.state.calibrated_light_paths.append(calibrated_light_path)
