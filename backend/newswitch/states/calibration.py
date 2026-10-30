"""The calibration state: the calibrated light paths."""

from dataclasses import dataclass, field

from newswitch.models.calibration import CalibratedLightPath
from newswitch.models.light_path import LightPathSnapshot


@dataclass
class CalibrationState:
    """Active illumination source configuration."""

    calibrated_light_paths: list[CalibratedLightPath] = field(default_factory=lambda: [])

    def get_calibrated_path(self, light_path_state: LightPathSnapshot) -> CalibratedLightPath:
        """Get the calibrated light path for a given light path configuration."""
        for calibrated_light_path in self.calibrated_light_paths:
            if calibrated_light_path.light_path_state_hash == light_path_state.transformation_hash:
                return calibrated_light_path
        raise ValueError(
            f"No calibrated light path found for light path {light_path_state.transformation_hash}"
        )
