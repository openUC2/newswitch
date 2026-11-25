"""A generic claibration manager"""

from __future__ import annotations

from collections.abc import Callable

from newswitch.calibration.models import CalibratedLightPath
from newswitch.calibration.states import CalibrationState


class CalibrationManager:
    """Keeps what was measured of each light path."""

    #: Called once a value of this part has changed.
    on_change: Callable[[], None] = staticmethod(lambda: None)

    def __init__(self, calibration_state: CalibrationState) -> None:
        """Initialize the CalibrationManager with the provided CalibrationState."""
        self.state = calibration_state

    def set_calibrated_state(self, calibrated_light_path: CalibratedLightPath) -> None:
        """Set the calibrated state for a light path configuration, replacing an earlier one."""
        key = calibrated_light_path.key
        self.state.calibrated_light_paths = [
            known for known in self.state.calibrated_light_paths if known.key != key
        ] + [calibrated_light_path]
        self.on_change()
