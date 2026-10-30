"""The detectors of a simulated instrument: everything a virtual detector does, other images."""

from __future__ import annotations

import numpy as np

from newswitch.drivers.optics.simulator import Simulator
from newswitch.drivers.virtual.virtual_detector import DetectorConfig, VirtualDetectorManager
from newswitch.instrument.parts import runtime_state, sensor_size
from newswitch.instrument.spec import Instrument
from newswitch.models.devices import Detector
from newswitch.states.detector import CameraState
from newswitch.states.filter_bank import FilterBankState
from newswitch.states.illumination import IlluminationState
from newswitch.states.objective import ObjectiveState
from newswitch.states.stage import StageState


class OpticsDetectorManager(VirtualDetectorManager):
    """Sessions, the live loop, binning and regions as a virtual detector; images from the optics."""

    def __init__(
        self,
        instrument: Instrument,
        camera_state: CameraState,
        stage_state: StageState,
        objective_state: ObjectiveState,
        illumination_state: IlluminationState,
        filter_bank_state: FilterBankState,
        detectors: list[Detector],
    ) -> None:
        """The detectors of `instrument`, which render from the shared states on every frame."""
        width, height = sensor_size(instrument)
        self.instrument = instrument
        self.simulator = Simulator(instrument)
        super().__init__(
            camera_state=camera_state,
            stage_state=stage_state,
            objective_state=objective_state,
            illumination_state=illumination_state,
            filter_bank_state=filter_bank_state,
            config=DetectorConfig(width=width, height=height),
            detectors=detectors,
        )

    def _generate_frame(self, detector: Detector) -> np.ndarray:
        """The whole sensor; `_read_out` cuts the region out and bins it, as for any detector."""
        name = self.instrument.detectors()[detector.slot - 1]
        state = runtime_state(
            self.instrument,
            self.state,
            self.stage_state,
            self.objective_state,
            self.illumination_state,
            self.filter_bank_state,
        )
        return self.simulator.render(name, state)
