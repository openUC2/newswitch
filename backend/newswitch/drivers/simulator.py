"""What is really there, and the images it really makes.

The only place that may read ``truth.yml``: how the real thing differs from its description. An
instrument without one is exactly what it says. It renders from what the compiler finds: errors the
optics can express go in there, and it adds what the description has no notion of. Everything else
has to find those out from the images, as with a real instrument.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import numpy as np
import yaml
from scipy import ndimage

from newswitch.instrument.compiler import compile_instrument
from newswitch.instrument.predict import Answer
from newswitch.instrument.spec import Instrument, Pattern
from newswitch.instrument.tracing import Errors

#: The hidden errors, in an instrument's folder.
TRUTH = "truth.yml"


def load_truth(instrument: Instrument) -> dict[str, Any]:
    """The hidden errors of `instrument`; none when it has no truth file."""
    path = instrument.folder / TRUTH
    return (yaml.safe_load(path.read_text()) or {}) if path.is_file() else {}


def optical_errors(instrument: Instrument) -> Errors | None:
    """The errors the tracer can apply; None when there are none."""
    truth = load_truth(instrument)
    if not truth:
        return None
    return Errors(objective_focal_factor=truth.get("objective_focal_error", 1.0))


def _sample(pattern: Pattern) -> np.ndarray:
    """Random beads: random so that a shift between two images has only one answer."""
    size = int(pattern.extent * 1000.0 / pattern.resolution)
    field = np.zeros((size, size), dtype=np.float32)
    if pattern.beads == 0:
        return field
    rng = np.random.default_rng(7)
    field[rng.integers(0, size, pattern.beads), rng.integers(0, size, pattern.beads)] = 1.0
    blurred = ndimage.gaussian_filter(field, pattern.radius / pattern.resolution)
    return blurred / blurred.max()


def _dtype(bit_depth: int) -> np.dtype:
    """The smallest array type that holds a detector's numbers."""
    for candidate in (np.uint8, np.uint16, np.uint32):
        if bit_depth <= np.iinfo(candidate).bits:
            return np.dtype(candidate)
    raise ValueError(f"no array type holds {bit_depth} bits")


class Simulator:
    """Renders what a detector sees under some state of the instrument."""

    def __init__(self, instrument: Instrument) -> None:
        """A simulator of `instrument`, with its hidden errors if it has any."""
        self.instrument = instrument
        self.truth = load_truth(instrument)
        self._table = compile_instrument(instrument, optical_errors(instrument))
        self._sample_images: dict[Pattern, np.ndarray] = {}
        self._noise = np.random.default_rng(11)

    def render(self, detector: str, state: Mapping[str, Any]) -> np.ndarray:
        """The whole sensor of `detector` under `state`, as uint16; `state` is in spec names."""
        answer = self._answer(detector, state)
        return self._expose(
            detector, answer, answer.electrons_by_source, *self._view(detector, state, answer)
        )

    def render_colors(self, detector: str, state: Mapping[str, Any]) -> dict[str, np.ndarray]:
        """A color camera's whole sensor: per color, what its band lets through, as uint16."""
        answer = self._answer(detector, state)
        beads, radius, positions, darkens = self._view(detector, state, answer)
        return {
            color: self._expose(detector, answer, electrons, beads, radius, positions, darkens)
            for color, electrons in answer.electrons_by_color.items()
        }

    def render_microtime(self, detector: str, state: Mapping[str, Any]) -> np.ndarray:
        """A detector timing its photons, as ``(m, H, W)``: each pixel's counts by arrival time.

        Counted, so with neither a camera's offset nor its read noise. What no fluorophore emits
        arrives with the pulse.
        """
        answer = self._answer(detector, state)
        counts = self._electrons(
            answer, answer.electrons_by_source, *self._view(detector, state, answer)
        )
        bins = next(axis for axis in self.instrument.detector_axes(detector) if axis.name == "m")
        fluorophore = self.instrument.simulation_at(state).fluorophore
        if fluorophore is None:
            shares = np.zeros(bins.size)
            shares[0] = 1.0
        else:
            edges = np.arange(bins.size + 1) * bins.step / 1000.0
            decay = np.exp(-edges / fluorophore.lifetime)
            shares = -np.diff(decay) / (1.0 - decay[-1])
        expected = np.clip(counts, 0, None)[np.newaxis] * shares[:, np.newaxis, np.newaxis]
        return self._noise.poisson(expected).clip(0, 65535).astype(np.uint16)

    def _answer(self, detector: str, state: Mapping[str, Any]) -> Answer:
        return self._table.answer(detector, {**state, f"{detector}.binning": 1})

    def _view(
        self, detector: str, state: Mapping[str, Any], answer: Answer
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
        """What of the sample lands on each pixel, how far each is from the middle (0 to 1), where
        each is from the middle along x and y in micrometres of the sample, and how much a bead takes
        of what passes through it."""
        pattern = self.instrument.simulation_at(state).pattern
        if pattern not in self._sample_images:
            self._sample_images[pattern] = _sample(pattern)
        sample = self._sample_images[pattern]
        width, height = answer.size
        columns, rows = np.meshgrid(np.arange(width, dtype=float), np.arange(height, dtype=float))

        # the filter's wedge shifts the whole image on the sensor
        wedge = self.truth.get("filter_wedge_px")
        if wedge and state.get(wedge["variable"]) == wedge["slot"]:
            columns = columns - wedge["shift"][0]
            rows = rows - wedge["shift"][1]
        centred = np.stack([columns - (width - 1) / 2, rows - (height - 1) / 2])

        # the camera is mounted slightly turned
        angle = math.radians(self.truth.get("camera_rotation_deg", {}).get(detector, 0.0))
        turn = np.array([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
        to_sample = turn @ np.array(answer.pixel_to_stage)
        sample_x, sample_y = np.tensordot(to_sample, centred, axes=1)

        to_raster = (sample.shape[0] - 1) / 2
        coordinates = np.stack(
            [
                (sample_y + answer.centre[1]) / pattern.resolution + to_raster,
                (sample_x + answer.centre[0]) / pattern.resolution + to_raster,
            ]
        )
        beads = ndimage.map_coordinates(sample, coordinates, order=1, mode="constant")
        radius = np.hypot(centred[0], centred[1]) / np.hypot((width - 1) / 2, (height - 1) / 2)
        scale = np.abs(np.diag(answer.pixel_to_stage))[:, np.newaxis, np.newaxis]
        return beads, radius, centred * scale, pattern.darkens

    def _expose(
        self,
        detector: str,
        answer: Answer,
        electrons_by_source: Mapping[str, float],
        beads: np.ndarray,
        radius: np.ndarray,
        positions: np.ndarray,
        darkens: float,
    ) -> np.ndarray:
        """The image `electrons_by_source` makes of `beads`, as this detector reads it out."""
        readout = self.instrument.cubes[detector].element.readout
        electrons = self._electrons(answer, electrons_by_source, beads, radius, positions, darkens)
        collected = self._noise.poisson(np.clip(electrons, 0, None)).clip(max=readout.full_well)
        read = self._noise.normal(0.0, readout.read_noise, electrons.shape)
        counts_per_electron = (
            answer.read_noise_counts / readout.read_noise if readout.read_noise else None
        )
        if counts_per_electron is None:
            counts_per_electron = 1.0 / readout.electrons_per_count
        counts = (collected + read) * counts_per_electron + readout.offset
        return np.rint(counts).clip(0, 2**readout.bit_depth - 1).astype(_dtype(readout.bit_depth))

    def _electrons(
        self,
        answer: Answer,
        light_by_source: Mapping[str, float],
        beads: np.ndarray,
        radius: np.ndarray,
        positions: np.ndarray,
        darkens: float,
    ) -> np.ndarray:
        """The electrons `light_by_source` is expected to make of `beads`, before any noise."""
        # What is emitted comes from the beads; what only passes is the same everywhere, but for what
        # they take of it: a mirror renders as a mirror.
        counts = np.zeros(beads.shape)
        for source, amount in light_by_source.items():
            direct = answer.direct_share_by_source.get(source, 0.0)
            lit = amount * (direct * (1.0 - darkens * beads) + (1.0 - direct) * beads)
            sheet = answer.sheet_by_source.get(source)
            if sheet is not None:
                # It widens away from its waist: fixed to the microscope, not to the stage.
                along = positions["xy".index(sheet["along"])]
                lit = lit / np.sqrt(1.0 + (along / sheet["rayleigh_um"]) ** 2)
            counts = counts + lit
        counts = ndimage.gaussian_filter(counts, answer.spot_px)
        return counts * (1.0 - (1.0 - answer.relative_illumination) * radius**2)


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
