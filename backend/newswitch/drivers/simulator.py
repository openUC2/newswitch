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
from newswitch.instrument.predict import Answer, state_key
from newswitch.instrument.spec import Instrument, Pattern, Stain
from newswitch.instrument.tracing import Errors, _gaussian, depth_of_field_um

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


def _beads(pattern: Pattern) -> np.ndarray:
    """Random beads, as ``(y, x, depth)`` in micrometres: random so that a shift has only one answer."""
    rng = np.random.default_rng(7)
    size = int(pattern.extent * 1000.0 / pattern.resolution)
    y, x = (
        (rng.integers(0, size, pattern.beads) - (size - 1) / 2) * pattern.resolution for _ in "yx"
    )
    return np.stack([y, x, rng.uniform(-0.5, 0.5, pattern.beads) * pattern.depth])


#: How far a bead's light is drawn, in widths of it; how dim one may be before it is not.
_REACH_SIGMAS = 4.0
_FAINTEST = 1e-3
#: A bead this wide or wider is blurred with others of about its width, so that a frame far out of
#: focus, where each would paint all of it, costs no more than one in focus.
_DRAWN_SIGMA = 8.0
#: How much wider each such group is than the last, and how finely it is computed, in its width.
_GROUP_RATIO = 1.08
_CELLS_PER_SIGMA = 3.0


def _add_blurred(
    field: np.ndarray,
    columns: np.ndarray,
    rows: np.ndarray,
    spread: np.ndarray,
    brightness: np.ndarray,
) -> None:
    """Add wide beads to `field`, computed on a grid as coarse as they are wide."""
    if not len(spread):
        return
    height, width = field.shape
    groups = np.floor(np.log(spread / _DRAWN_SIGMA) / np.log(_GROUP_RATIO)).astype(int)
    for group in np.unique(groups):
        chosen = groups == group
        sigma = _DRAWN_SIGMA * _GROUP_RATIO ** (group + 0.5)
        cell = max(sigma / _CELLS_PER_SIGMA, 1.0)
        margin = _REACH_SIGMAS * sigma * _GROUP_RATIO
        size = (int((height + 2 * margin) / cell) + 3, int((width + 2 * margin) / cell) + 3)
        coarse = np.zeros(size)
        at_row = (rows[chosen] + margin) / cell
        at_column = (columns[chosen] + margin) / cell
        # Each keeps its light, for having been given the width of its group.
        weight = (
            brightness[chosen] * (spread[chosen] / sigma) ** 2 * 2.0 * np.pi * (sigma / cell) ** 2
        )
        row, column = np.floor(at_row).astype(int), np.floor(at_column).astype(int)
        inside = (row >= 0) & (row < size[0] - 1) & (column >= 0) & (column < size[1] - 1)
        row, column, weight = row[inside], column[inside], weight[inside]
        down, across = (at_row[inside] - row), (at_column[inside] - column)
        np.add.at(coarse, (row, column), weight * (1 - down) * (1 - across))
        np.add.at(coarse, (row, column + 1), weight * (1 - down) * across)
        np.add.at(coarse, (row + 1, column), weight * down * (1 - across))
        np.add.at(coarse, (row + 1, column + 1), weight * down * across)
        blurred = ndimage.gaussian_filter(coarse, sigma / cell, mode="constant")
        pixels = np.meshgrid(
            (np.arange(height) + margin) / cell, (np.arange(width) + margin) / cell, indexing="ij"
        )
        field += ndimage.map_coordinates(blurred, pixels, order=1, mode="nearest")


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
        self._bead_positions: dict[Pattern, np.ndarray] = {}
        self._noise = np.random.default_rng(11)

    def render(self, detector: str, state: Mapping[str, Any]) -> np.ndarray:
        """The whole sensor of `detector` under `state`, as uint16; `state` is in spec names."""
        answer = self._answer(detector, state)
        return self._expose(
            detector,
            answer,
            answer.electrons_by_source,
            *self._view(detector, state, answer),
            self._through(self._stains(detector, state, answer), answer.band_nm or 550.0),
        )

    def render_colors(self, detector: str, state: Mapping[str, Any]) -> dict[str, np.ndarray]:
        """A color camera's whole sensor: per color, what its band lets through, as uint16."""
        answer = self._answer(detector, state)
        view = self._view(detector, state, answer)
        colors = self.instrument.cubes[detector].element_at(state).colors
        stains = self._stains(detector, state, answer)
        return {
            color: self._expose(
                detector,
                answer,
                electrons,
                *view,
                self._through(stains, colors[color].center),
            )
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
        width, height = answer.size
        columns, rows = np.meshgrid(np.arange(width, dtype=float), np.arange(height, dtype=float))
        centred = np.stack([columns - (width - 1) / 2, rows - (height - 1) / 2])
        beads = self._slice(detector, state, answer, pattern)
        radius = np.hypot(centred[0], centred[1]) / np.hypot((width - 1) / 2, (height - 1) / 2)
        scale = np.abs(np.diag(answer.pixel_to_stage))[:, np.newaxis, np.newaxis]
        return beads, radius, centred * scale, pattern.darkens

    def _stains(
        self, detector: str, state: Mapping[str, Any], answer: Answer
    ) -> list[tuple[Stain, np.ndarray]]:
        """Each stain, with how much of it lands on each pixel."""
        return [
            (stain, np.minimum(self._slice(detector, state, answer, stain.pattern), 1.0))
            for stain in self.instrument.simulation_at(state).stains.values()
        ]

    @staticmethod
    def _through(
        stains: list[tuple[Stain, np.ndarray]], wavelength_nm: float
    ) -> np.ndarray | float:
        """What `stains` let through to each pixel, of light of `wavelength_nm`."""
        through: np.ndarray | float = 1.0
        for stain, there in stains:
            amount = float(_gaussian(np.array(wavelength_nm), stain.center, stain.width))
            through = through * (1.0 - stain.darkens * amount * there)
        return through

    def _slice(
        self, detector: str, state: Mapping[str, Any], answer: Answer, pattern: Pattern
    ) -> np.ndarray:
        """What of the sample lands on each pixel: each bead lit as far as it is, spread as far as
        it is out of focus, and with its light conserved."""
        # the camera is mounted slightly turned
        angle = math.radians(self.truth.get("camera_rotation_deg", {}).get(detector, 0.0))
        turn = np.array([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
        to_sample = turn @ np.array(answer.pixel_to_stage)
        # the filter's wedge shifts the whole image on the sensor
        wedge = self.truth.get("filter_wedge_px")
        shift = (
            wedge["shift"]
            if wedge and state.get(wedge["variable"]) == wedge["slot"]
            else (0.0, 0.0)
        )
        width, height = answer.size
        field = np.zeros((height, width))
        if pattern not in self._bead_positions:
            self._bead_positions[pattern] = _beads(pattern)
        y, x, depth = self._bead_positions[pattern]

        moves = self._table.states[state_key(self.instrument, state)][detector]["focus"]["moves"]
        sample_moves = {move.name for move in self.instrument.sample_moves()}
        sample_um = sum(float(state[name]) for name in moves if name in sample_moves)
        lens_um = sum(float(state[name]) for name in moves if name not in sample_moves)
        lit = np.ones(depth.shape)
        for sheet in answer.sheet_by_source.values():
            plane = sum(float(state[move.name]) for move in self.instrument.sheet_moves())
            lit = lit * np.exp(-2.0 * ((depth + sample_um - plane) / sheet["waist_um"]) ** 2)
        if self.instrument.scanner_of(detector) is not None:
            # A focused spot and what it passes back section the sample: nothing else is lit.
            section = depth_of_field_um(self.instrument, detector, state)
            lit = lit * np.exp(-2.0 * ((depth + sample_um + lens_um) / section) ** 2)

        pixel_um = math.hypot(to_sample[0, 0], to_sample[1, 0])
        grown = pattern.radius / pixel_um
        spread = np.hypot(grown, answer.blur_px_per_um * (depth + sample_um + lens_um))
        brightness = lit * (grown / spread) ** 2
        columns, rows = np.linalg.inv(to_sample) @ np.stack(
            [x - answer.centre[0], y - answer.centre[1]]
        )
        columns = columns + (width - 1) / 2 + shift[0]
        rows = rows + (height - 1) / 2 + shift[1]
        reach = _REACH_SIGMAS * spread
        seen = (
            (brightness > _FAINTEST)
            & (columns > -reach)
            & (columns < width + reach)
            & (rows > -reach)
            & (rows < height + reach)
        )
        columns, rows, spread, brightness = (
            columns[seen],
            rows[seen],
            spread[seen],
            brightness[seen],
        )
        near = spread < _DRAWN_SIGMA
        for column, row, sigma, bright in zip(
            columns[near], rows[near], spread[near], brightness[near]
        ):
            far = _REACH_SIGMAS * sigma
            left, right = max(int(column - far), 0), min(int(column + far) + 2, width)
            top, bottom = max(int(row - far), 0), min(int(row + far) + 2, height)
            across = np.exp(-0.5 * ((np.arange(left, right) - column) / sigma) ** 2)
            down = np.exp(-0.5 * ((np.arange(top, bottom) - row) / sigma) ** 2)
            field[top:bottom, left:right] += bright * np.outer(down, across)
        _add_blurred(field, columns[~near], rows[~near], spread[~near], brightness[~near])
        return field

    def _expose(
        self,
        detector: str,
        answer: Answer,
        electrons_by_source: Mapping[str, float],
        beads: np.ndarray,
        radius: np.ndarray,
        positions: np.ndarray,
        darkens: float,
        stained: np.ndarray | float = 1.0,
    ) -> np.ndarray:
        """The image `electrons_by_source` makes of `beads`, as this detector reads it out."""
        readout = self.instrument.cubes[detector].element.readout
        electrons = self._electrons(
            answer, electrons_by_source, beads, radius, positions, darkens, stained
        )
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
        stained: np.ndarray | float = 1.0,
    ) -> np.ndarray:
        """The electrons `light_by_source` is expected to make of `beads`, before any noise."""
        # What is emitted comes from the beads; what only passes is the same everywhere, but for what
        # they take of it: a mirror renders as a mirror.
        counts = np.zeros(beads.shape)
        for source, amount in light_by_source.items():
            direct = answer.direct_share_by_source.get(source, 0.0)
            taken = darkens * np.minimum(beads, 1.0)
            lit = amount * (direct * (1.0 - taken) * stained + (1.0 - direct) * beads)
            sheet = answer.sheet_by_source.get(source)
            if sheet is not None:
                # It widens away from its waist: fixed to the microscope, not to the stage.
                along = positions["xy".index(sheet["along"])]
                lit = lit / np.sqrt(1.0 + (along / sheet["rayleigh_um"]) ** 2)
            counts = counts + lit
        counts = ndimage.gaussian_filter(counts, answer.in_focus_px)
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
