"""What an image was taken under: where its pixels are on the sample, and the light path it came
through."""

from __future__ import annotations

from datetime import datetime

import numpy as np

from newswitch.models.frames import Metadata
from newswitch.models.light_path import LightPath, LightPathSnapshot
from newswitch.services.optics import OpticsManager
from newswitch.services.space import SpaceManager
from newswitch.states.detector import DetectorState


class MetadataManager:
    """Says where a detector's pixels are, as the space says (`SpaceManager.placement`)."""

    def __init__(
        self, space: SpaceManager, optics: OpticsManager, detector_state: DetectorState
    ) -> None:
        """A manager placing by `space`, with the light paths of `optics`."""
        self._space = space
        self._optics = optics
        self._detector_state = detector_state

    def get_metadata_for_light_path(self, light_path: LightPath) -> Metadata:
        """Where the pixels of an image through `light_path` are, under the current values."""
        snapshot = self._optics.snapshot(light_path)
        placement = self._space.placement(light_path.detector)
        height, width = self._detector_state.get(light_path.detector).plane()
        return Metadata(
            affine_matrix=placement.tolist(),
            fov_width=float(np.hypot(*placement[:2, 0])) * width,
            fov_height=float(np.hypot(*placement[:2, 1])) * height,
            light_state=snapshot,
            acquisition_time=datetime.now().isoformat(),
            sample=self._space.sample_of(light_path.detector),
        )

    def get_current_state_for_light_path(self, light_path: LightPath) -> LightPathSnapshot:
        """`light_path` as things are now, keyed by what a calibration of it depends on."""
        return self._optics.snapshot(light_path)
