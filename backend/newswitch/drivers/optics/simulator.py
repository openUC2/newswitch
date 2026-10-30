"""What is really there, and the images it really makes.

The only place that may read ``truth.yml``: how the real thing differs from its description. An
instrument without one is exactly what it says. It renders from a compiled table, so it needs no
optics library: errors the optics can express are in that table (`TRUTH_TABLE`), and it adds what
the description has no notion of. Everything else has to find those out from the images, as with
a real instrument.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import numpy as np
import yaml
from scipy import ndimage

from newswitch.instrument.predict import COMPILED, Compiled
from newswitch.instrument.spec import Instrument
from newswitch.instrument.tracing import Errors

#: The hidden errors, in an instrument's folder.
TRUTH = "truth.yml"
#: What the compiler found with those errors applied, in an instrument's folder.
TRUTH_TABLE = "compiled.truth.json"

#: The sample: random beads on a slide, and how finely it is rendered.
_SAMPLE_HALF_WIDTH_UM = 3000.0
_SAMPLE_UM_PER_PX = 2.0
_BEADS = 3600
_BEAD_RADIUS_UM = 10.0
#: The camera's offset and read noise, in counts.
_OFFSET = 100.0
_READ_NOISE = 5.0


def load_truth(instrument: Instrument) -> dict[str, Any]:
    """The hidden errors of `instrument`; none when it has no truth file."""
    path = instrument.folder / TRUTH
    return (yaml.safe_load(path.read_text()) or {}) if path.is_file() else {}


def optical_errors(instrument: Instrument) -> Errors | None:
    """The errors the tracer can apply, for compiling `TRUTH_TABLE`; None when there are none."""
    truth = load_truth(instrument)
    if not truth:
        return None
    return Errors(objective_focal_factor=truth.get("objective_focal_error", 1.0))


def _sample() -> np.ndarray:
    """Random beads: random so that a shift between two images has only one answer."""
    size = int(2 * _SAMPLE_HALF_WIDTH_UM / _SAMPLE_UM_PER_PX)
    field = np.zeros((size, size), dtype=np.float32)
    rng = np.random.default_rng(7)
    field[rng.integers(0, size, _BEADS), rng.integers(0, size, _BEADS)] = 1.0
    blurred = ndimage.gaussian_filter(field, _BEAD_RADIUS_UM / _SAMPLE_UM_PER_PX)
    return blurred / blurred.max()


class Simulator:
    """Renders what a detector sees under some state of the instrument."""

    def __init__(self, instrument: Instrument) -> None:
        """A simulator of `instrument`, with its hidden errors if it has any."""
        self.instrument = instrument
        self.truth = load_truth(instrument)
        self._table = Compiled.load(instrument, TRUTH_TABLE if self.truth else COMPILED)
        self._sample_image: np.ndarray | None = None
        self._noise = np.random.default_rng(11)
        self._transmitted = {
            source
            for source in instrument.sources()
            if any(
                route[-1].side == "transmitted"
                for route in instrument.routes(
                    instrument.illumination, source, instrument.sample_cube()
                )
            )
        }

    def render(self, detector: str, state: Mapping[str, Any]) -> np.ndarray:
        """The whole sensor of `detector` under `state`, as uint16; `state` is in spec names."""
        if self._sample_image is None:
            self._sample_image = _sample()
        answer = self._table.answer(detector, {**state, f"{detector}.binning": 1})
        width, height = answer.size
        columns, rows = np.meshgrid(np.arange(width, dtype=float), np.arange(height, dtype=float))

        # the filter's wedge shifts the whole image on the sensor
        wedge = self.truth.get("filter_wedge_px")
        if wedge and state.get("filter-wheel.slot") == wedge["slot"]:
            columns = columns - wedge["shift"][0]
            rows = rows - wedge["shift"][1]
        centred = np.stack([columns - (width - 1) / 2, rows - (height - 1) / 2])

        # the camera is mounted slightly turned
        angle = math.radians(self.truth.get("camera_rotation_deg", {}).get(detector, 0.0))
        turn = np.array([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
        to_sample = turn @ np.array(answer.pixel_to_stage)
        sample_x, sample_y = np.tensordot(to_sample, centred, axes=1)

        to_raster = (self._sample_image.shape[0] - 1) / 2
        coordinates = np.stack(
            [
                (sample_y + answer.centre[1]) / _SAMPLE_UM_PER_PX + to_raster,
                (sample_x + answer.centre[0]) / _SAMPLE_UM_PER_PX + to_raster,
            ]
        )
        beads = ndimage.map_coordinates(self._sample_image, coordinates, order=1, mode="constant")

        # what emits comes from the beads; what passes through is darkened by them
        counts = np.zeros(beads.shape)
        for source, amount in answer.light_by_source.items():
            counts = counts + amount * (
                (1.0 - 0.6 * beads) if source in self._transmitted else beads
            )
        counts = ndimage.gaussian_filter(counts, answer.spot_px)

        radius = np.hypot(centred[0], centred[1]) / np.hypot((width - 1) / 2, (height - 1) / 2)
        counts = counts * (1.0 - (1.0 - answer.relative_illumination) * radius**2)
        noisy = self._noise.poisson(np.clip(counts, 0, None)) + self._noise.normal(
            _OFFSET, _READ_NOISE, counts.shape
        )
        return noisy.clip(0, 65535).astype(np.uint16)


class SimulatedMicroscope:
    """A simulator with state of its own: set it and take images, without a server around it."""

    def __init__(self, instrument: Instrument) -> None:
        """At the initial values of `instrument`."""
        self.simulator = Simulator(instrument)
        self.truth = self.simulator.truth
        self.state: dict[str, Any] = instrument.initial_state()

    def set(self, values: Mapping[str, Any]) -> None:
        """Set variables by their full names, such as ``{"stage.x": 10.0}``."""
        for name, value in values.items():
            if name not in self.state:
                raise KeyError(name)
            self.state[name] = value

    def image(self, detector: str) -> np.ndarray:
        """Take an image with `detector`."""
        return self.simulator.render(detector, self.state)
