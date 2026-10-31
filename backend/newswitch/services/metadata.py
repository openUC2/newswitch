"""What an image was taken under: where its pixels are, and the light path it came through."""

from __future__ import annotations

from datetime import datetime

import numpy as np

from newswitch.models.frames import Metadata
from newswitch.models.light_path import LightPath, LightPathSnapshot
from newswitch.services.optics import OpticsManager
from newswitch.states.calibration import CalibrationState
from newswitch.states.stage import StageState


class MetadataManager:
    """Says where a detector's pixels are: as calibrated, or else as the optics predict."""

    def __init__(
        self,
        stage_state: StageState,
        calibration_state: CalibrationState,
        optics: OpticsManager,
    ) -> None:
        """A manager reading those states, with `optics` for what no calibration covers."""
        self._stage_state = stage_state
        self._calibration_state = calibration_state
        self._optics = optics

    def get_metadata_for_light_path(self, light_path: LightPath) -> Metadata:
        """Where the pixels of an image through `light_path` are, under the current values."""
        snapshot = self._optics.snapshot(light_path)
        try:
            calibration = self._calibration_state.get_calibrated_path(light_path_state=snapshot)
        except ValueError:
            slot = self._optics.instrument.detectors().index(light_path.detector) + 1
            calibration = self._optics.predicted(slot)
        combined = np.dot(
            np.array(calibration.affine_matrix), np.array(self._stage_state.as_affine_matrix())
        )
        return Metadata(
            affine_matrix=combined.tolist(),
            fov_height=calibration.fov_height,
            fov_width=calibration.fov_width,
            light_state=snapshot,
            acquisition_time=datetime.now().isoformat(),
        )

    def get_current_state_for_light_path(self, light_path: LightPath) -> LightPathSnapshot:
        """`light_path` as things are now, keyed by what a calibration of it depends on."""
        return self._optics.snapshot(light_path)
