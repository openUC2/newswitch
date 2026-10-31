"""The detectors of a simulated instrument: everything a virtual detector does, other images."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

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


def _times_photons(detector: Detector) -> bool:
    """Whether `detector` delivers when its photons arrive, as an axis of its own."""
    return any(axis.name == "m" for axis in detector.axes)


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

    def _runtime_state(self) -> dict[str, Any]:
        return runtime_state(
            self.instrument,
            self.state,
            self.stage_state,
            self.objective_state,
            self.illumination_state,
            self.filter_bank_state,
        )

    def _generate_frame(self, detector: Detector) -> np.ndarray:
        """The whole sensor; `_read_out` cuts the region out and bins it, as for any detector.

        What a color camera shows on its own (the live view, an autofocus) is the mean of its
        colors: everything that expects one image gets one.
        """
        name = self.instrument.detectors()[detector.slot - 1]
        if detector.colors:
            colors = self.simulator.render_colors(name, self._runtime_state())
            return np.mean(list(colors.values()), axis=0).astype(np.uint16)
        if _times_photons(detector):
            histogram = self.simulator.render_microtime(name, self._runtime_state())
            return histogram.sum(axis=0).clip(0, 65535).astype(np.uint16)
        return self.simulator.render(name, self._runtime_state())

    def capture_stack(self, slot: int, planes: int) -> Iterator[np.ndarray]:
        """Each event of the detector steps the stage, as the wire says; the sweep ends on its last plane."""
        steps = [
            axis.step for axis in self.state.get_detector_for_slot(slot).axes if axis.name == "z"
        ]
        if not steps:
            raise ValueError(f"Detector {slot} delivers no z")
        first = self.stage_state.z
        for plane in range(planes):
            self.stage_state.z = first + plane * steps[0]
            yield self.capture_channels(slot)

    def capture_channels(self, slot: int) -> np.ndarray:
        """One exposure as ``(c, H, W)``, in the order of the detector's `colors`.

        A detector timing its photons gives ``(c, m, H, W)``.
        """
        detector = self.state.get_detector_for_slot(slot)
        name = self.instrument.detectors()[slot - 1]
        if _times_photons(detector):
            histogram = self.simulator.render_microtime(name, self._runtime_state())
            return np.stack([self._read_out(plane, detector) for plane in histogram])[np.newaxis]
        if not detector.colors:
            return super().capture_channels(slot)
        colors = self.simulator.render_colors(name, self._runtime_state())
        return np.stack([self._read_out(colors[color], detector) for color in detector.colors])
