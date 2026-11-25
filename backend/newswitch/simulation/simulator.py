"""What is really there, and the images it really makes.

It alone takes in ``truth.yml`` (`newswitch.simulation.truth`): how the real thing differs from its
description. An instrument without one is exactly what it says. It renders from what the compiler finds: errors the
optics can express go in there, and it adds what the description has no notion of. Everything else
has to find those out from the images, as with a real instrument.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from typing import Any

import numpy as np
from scipy import ndimage

from newswitch.instrument.compiler import compile_instrument
from newswitch.instrument.errors import SpecError
from newswitch.instrument.predict import Answer
from newswitch.instrument.space import holder_to_stage
from newswitch.instrument.spec import (
    Instrument,
    Pattern,
    PointDetector,
    Probe,
    SimulatedSlide,
    Simulation,
    Stain,
    place_of,
)
from newswitch.instrument.tracing import depth_of_field_um, gaussian
from newswitch.simulation import light
from newswitch.simulation.truth import load_truth, optical_errors

#: What the air beside the sample is, unless the truth says otherwise.
AIR_TEMPERATURE_C = 22.0


#: How long a spike lasts, and how many reaches away a cell still counts for an electrode.
SPIKE_MS = 1.5
SPIKE_REACHES = 5.0
#: The seeds of the noise of an electrode array, and of when its cells fire.
NOISE_SEED = 13
SPIKE_SEED = 17


def _spike(samples: int) -> np.ndarray:
    """An extracellular spike `samples` long, its trough -1: down sharply, then up a little."""
    t = np.linspace(0.0, 1.0, max(samples, 2))
    wave = -np.exp(-(((t - 0.25) / 0.08) ** 2)) + 0.4 * np.exp(-(((t - 0.55) / 0.15) ** 2))
    return wave / -wave.min()


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
#: What a simulation without beads (a bare slide) has of them: none.
_NO_BEADS = Pattern(beads=0, radius="1 um", depth="1 um")  # type: ignore[arg-type]
_FAINTEST = 1e-3
#: How many pixels of a frame are worth drawing bead by bead, narrowest first. The rest are blurred
#: together, so that a frame far out of focus, where each would paint all of it, costs no more.
_DRAWN_PIXELS = 4_000_000
#: How much wider each such group is than the last, and how finely it is computed, in its width.
_GROUP_RATIO = 1.25
_CELLS_PER_SIGMA = 3.0


def _add_blurred(
    field: np.ndarray,
    columns: np.ndarray,
    rows: np.ndarray,
    spread: np.ndarray,
    brightness: np.ndarray,
) -> None:
    """Add wide beads to `field`, on a grid as coarse as they are wide.

    Each goes to the two groups around its width, in proportion, keeping its light: a bead changing
    width changes the image smoothly, or a focus metric would see the steps and not the focus.
    """
    if not len(spread):
        return
    height, width = field.shape
    place = np.log(spread) / np.log(_GROUP_RATIO)
    lower = np.floor(place).astype(int)
    upper_share = place - lower
    for group in range(int(lower.min()), int(lower.max()) + 2):
        sigma = _GROUP_RATIO**group
        share = np.where(lower == group, 1.0 - upper_share, 0.0) + np.where(
            lower + 1 == group, upper_share, 0.0
        )
        chosen = share > 0.0
        if not chosen.any():
            continue
        cell = max(sigma / _CELLS_PER_SIGMA, 1.0)
        margin = _REACH_SIGMAS * sigma * _GROUP_RATIO
        size = (int((height + 2 * margin) / cell) + 3, int((width + 2 * margin) / cell) + 3)
        coarse = np.zeros(size)
        at_row = (rows[chosen] + margin) / cell
        at_column = (columns[chosen] + margin) / cell
        weight = (
            share[chosen]
            * brightness[chosen]
            * (spread[chosen] / sigma) ** 2
            * 2.0
            * np.pi
            * (sigma / cell) ** 2
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
        """A simulator of `instrument`, with its hidden errors if it has any.

        Raises:
            SpecError: A simulation lacks what the simulator needs to draw it (`problems`).
        """
        found = problems(instrument)
        if found:
            raise SpecError(f"{instrument.name}: {'; '.join(found)}")
        self.instrument = instrument
        self.truth = load_truth(instrument)
        self._grid = light.grid(instrument)
        self._table = compile_instrument(instrument, optical_errors(instrument), self._grid)
        self.on: dict[str, str] = {
            sample: instrument.sample_holder(sample).simulation for sample in instrument.samples()
        }
        """Which of its simulations is on each sample: what its holder says, until `put`."""
        self._bead_positions: dict[tuple[Pattern, str, str | None], np.ndarray] = {}
        self._noise = np.random.default_rng(11)
        self.mounted: Callable[[str], str | None] = lambda sample: (
            self.instrument.sample_holder(sample).mounted
        )
        """Which holder each sample is mounted on: the space says (`newswitch.services.space`)."""

    def simulation_of(self, sample: str) -> Simulation:
        """What is on `sample` now."""
        return self.instrument.sample_holder(sample).simulations[self.on[sample]]

    def put(self, sample: str, simulation: str) -> None:
        """Put another of its simulations on `sample`.

        Raises:
            KeyError: Its holder has no such simulation.
        """
        if simulation not in self.instrument.sample_holder(sample).simulations:
            raise KeyError(f"{sample}: no simulation {simulation!r}")
        self.on[sample] = simulation

    def read_point(self, probe: str) -> float:
        """What a probe at a point reads now, as its model says, strayed by its noise.

        ``air``: the air beside the sample (``air_temperature_c`` in the truth, 22 °C without one).
        """
        element = self.instrument.cubes[probe].element
        assert isinstance(element, Probe)
        match element.model.kind:
            case "air":
                value = float(self.truth.get("air_temperature_c", AIR_TEMPERATURE_C))
            case kind:
                raise ValueError(f"{probe}: a {kind} model reads no single point")
        noise = element.model.noise
        return value + float(self._noise.normal(0.0, noise)) if noise else value

    def potentials(self, probe: str, t0_s: float, state: Mapping[str, Any]) -> np.ndarray:
        """What a probe reading a grid samples in the block starting `t0_s` seconds into its clock,
        as ``(samples, rows, columns)`` in its unit: its noise, and the spikes of the cells nearby.

        The cells are the beads the cameras draw (`beads_in_sample`), firing at random as the
        sample's ``electrical`` says; each electrode picks up a cell's spike the weaker the farther
        it is. Nothing mounted that has the grid, nothing but noise; a sample that does not fire,
        likewise. The same block is the same however often it is read, and blocks join.
        """
        element = self.instrument.cubes[probe].element
        assert isinstance(element, Probe) and element.reads is not None
        assert element.sampling is not None, f"{probe} samples no time"
        (sample,) = self.instrument.samples_of(probe)
        rate, n = element.sampling.rate, element.sampling.samples
        start = round(t0_s * rate)
        noise = np.random.default_rng([NOISE_SEED, start])
        holder_name = self.mounted(sample)
        holder = (
            None
            if holder_name is None
            else self.instrument.sample_holder(sample).holders[holder_name].holder
        )
        grid = None if holder is None else holder.grids.get(element.reads.grid)
        if grid is None:
            rows, columns = (
                self.instrument.grid_of(probe).rows,
                self.instrument.grid_of(probe).columns,
            )
            return noise.normal(0.0, element.model.noise, (n, rows, columns)).astype(np.float32)
        out = noise.normal(0.0, element.model.noise, (n, grid.rows, grid.columns))
        simulation = self.simulation_of(sample)
        electrical = simulation.electrical
        if electrical is None:
            return out.astype(np.float32)
        y, x, depth = self.beads_in_sample(simulation.pattern or _NO_BEADS, sample)
        columns_um = (grid.a1.x + np.arange(grid.columns) * grid.pitch.x) * 1000.0
        rows_um = (grid.a1.y + np.arange(grid.rows) * grid.pitch.y) * 1000.0
        dy = y[:, None, None] - rows_um[None, :, None]
        dx = x[:, None, None] - columns_um[None, None, :]
        distance = np.sqrt(dy**2 + dx**2 + depth[:, None, None] ** 2)
        near = np.nonzero(distance.min(axis=(1, 2)) < SPIKE_REACHES * electrical.reach)[0]
        amplitude = electrical.amplitude * np.exp(-distance[near] / electrical.reach)
        wave = _spike(round(SPIKE_MS * rate / 1000.0))
        expected = electrical.rate * n / rate
        for index, cell in enumerate(near):
            fires = np.random.default_rng([SPIKE_SEED, int(cell), start])
            for at in fires.integers(0, n, fires.poisson(expected)):
                length = min(len(wave), n - at)
                out[at : at + length] += wave[:length, None, None] * amplitude[index]
        return out.astype(np.float32)

    def beads_in_sample(self, pattern: Pattern, sample: str) -> np.ndarray:
        """Where `pattern`'s beads are on what `sample` is mounted on, as ``(y, x, depth)`` in its
        sample micrometres.

        On a slide or a dish centred on it, on a plate in every well; with nothing mounted, centred
        on its stage's 0.
        """
        holder_name = self.mounted(sample)
        key = (pattern, sample, holder_name)
        if key not in self._bead_positions:
            beads = _beads(pattern)
            if holder_name is not None:
                holder = self.instrument.sample_holder(sample).holders[holder_name].holder
                wells = holder.grids.get("well")
                if wells is None:
                    middle = (holder.extent.y * 500.0, holder.extent.x * 500.0, 0.0)
                    beads = beads + np.array(middle)[:, np.newaxis]
                else:
                    radius = (wells.place.diameter or wells.place.size or 0.0) * 500.0
                    inside = beads[:, np.hypot(beads[0], beads[1]) <= radius]
                    beads = np.concatenate(
                        [
                            inside + np.array([y * 1000.0, x * 1000.0, 0.0])[:, np.newaxis]
                            for x, y in wells.places().values()
                        ],
                        axis=1,
                    )
            self._bead_positions[key] = beads
        return self._bead_positions[key]

    def beads_on_stage(self, pattern: Pattern, sample: str) -> np.ndarray:
        """`beads_in_sample` where they really are on `sample`'s stage: through the mount as it
        truly is, the one described shifted by the truth's ``mount_offset_um`` (one offset, or one
        per sample cube)."""
        beads = self.beads_in_sample(pattern, sample)
        holder_name = self.mounted(sample)
        if holder_name is None:
            return beads
        mount = self.instrument.sample_holder(sample).holders[holder_name].mount
        offset = self.truth.get("mount_offset_um", {})
        if sample in offset:
            offset = offset[sample]
        matrix = holder_to_stage(mount, (offset.get("x", 0.0), offset.get("y", 0.0)))
        y, x, depth = beads
        on_stage = matrix[:2, :2] @ np.stack([x, y]) + matrix[:2, 3:4]
        return np.stack([on_stage[1], on_stage[0], depth])

    def _dark(self, detector: str) -> np.ndarray:
        """The whole sensor of `detector` with no light on it: its offset and its read noise."""
        *_, axis_y, axis_x = self.instrument.detector_axes(detector)
        readout = self.instrument.cubes[detector].element.readout
        read = self._noise.normal(0.0, readout.read_noise, (axis_y.size, axis_x.size))
        counts = read / readout.electrons_per_count + readout.offset
        return np.rint(counts).clip(0, 2**readout.bit_depth - 1).astype(_dtype(readout.bit_depth))

    def render(self, detector: str, state: Mapping[str, Any]) -> np.ndarray:
        """The whole sensor of `detector` under `state`, as uint16; `state` is in spec names. Dark,
        where the switches send its light elsewhere."""
        if self.instrument.sample_of(detector, state) is None:
            return self._dark(detector)
        answer = self._answer(detector, state)
        return self._expose(
            detector,
            answer,
            answer.electrons_by_source,
            *self._view(detector, state, answer),
            self._through(self._stains(detector, state, answer), answer.band_nm or 550.0)
            * self._opening(detector, state, answer),
        )

    def render_colors(self, detector: str, state: Mapping[str, Any]) -> dict[str, np.ndarray]:
        """A color camera's whole sensor: per color, what its band lets through, as uint16."""
        if self.instrument.sample_of(detector, state) is None:
            colors = self.instrument.cubes[detector].element_at(state).colors
            return {color: self._dark(detector) for color in colors}
        answer = self._answer(detector, state)
        view = self._view(detector, state, answer)
        colors = self.instrument.cubes[detector].element_at(state).colors
        stains = self._stains(detector, state, answer)
        opening = self._opening(detector, state, answer)
        return {
            color: self._expose(
                detector,
                answer,
                electrons,
                *view,
                self._through(stains, colors[color].center) * opening,
            )
            for color, electrons in answer.electrons_by_color.items()
        }

    def render_microtime(self, detector: str, state: Mapping[str, Any]) -> np.ndarray:
        """A detector timing its photons, as ``(m, H, W)``: each pixel's counts by arrival time.

        Counted, so with neither a camera's offset nor its read noise. What no fluorophore emits
        arrives with the pulse. Nothing at all, where the switches send its light elsewhere.
        """
        bins = next(axis for axis in self.instrument.detector_axes(detector) if axis.name == "m")
        if self.instrument.sample_of(detector, state) is None:
            *_, axis_y, axis_x = self.instrument.detector_axes(detector)
            return np.zeros((bins.size, axis_y.size, axis_x.size), np.uint16)
        answer = self._answer(detector, state)
        counts = self._electrons(
            answer, answer.electrons_by_source, *self._view(detector, state, answer)
        )
        fluorophore = self.simulation_of(self.instrument.seen_sample(detector, state)).fluorophore
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
        """What the optics make of what is on the sample `detector` sees: its light, and how deep
        it is."""
        simulation = self.simulation_of(self.instrument.seen_sample(detector, state))
        return self._table.answer(
            detector,
            {**state, f"{detector}.binning": 1},
            couple=lambda found: light.coupling(found, simulation, self._grid),
            depth_um=0.0 if simulation.pattern is None else simulation.pattern.depth,
        )

    def _view(
        self, detector: str, state: Mapping[str, Any], answer: Answer
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
        """What of the sample lands on each pixel, how far each is from the middle (0 to 1), where
        each is from the middle along x and y in micrometres of the sample, and how much a bead takes
        of what passes through it."""
        pattern = (
            self.simulation_of(self.instrument.seen_sample(detector, state)).pattern or _NO_BEADS
        )
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
            for stain in self.simulation_of(
                self.instrument.seen_sample(detector, state)
            ).stains.values()
        ]

    @staticmethod
    def _through(
        stains: list[tuple[Stain, np.ndarray]], wavelength_nm: float
    ) -> np.ndarray | float:
        """What `stains` let through to each pixel, of light of `wavelength_nm`."""
        through: np.ndarray | float = 1.0
        for stain, there in stains:
            amount = float(gaussian(np.array(wavelength_nm), stain.center, stain.width))
            through = through * (1.0 - stain.darkens * amount * there)
        return through

    def _sensor(
        self, detector: str, state: Mapping[str, Any], answer: Answer
    ) -> tuple[np.ndarray, tuple[float, float]]:
        """How a pixel steps on the stage as the camera truly is (slightly turned, by the truth),
        and how far the filter's wedge shifts the image on the sensor, in pixels."""
        angle = math.radians(self.truth.get("camera_rotation_deg", {}).get(detector, 0.0))
        turn = np.array([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
        to_sample = turn @ np.array(answer.pixel_to_stage)
        wedge = self.truth.get("filter_wedge_px")
        shift = (
            wedge["shift"]
            if wedge and state.get(wedge["variable"]) == wedge["slot"]
            else (0.0, 0.0)
        )
        return to_sample, shift

    def holes_on_stage(self, slide: SimulatedSlide, sample: str) -> np.ndarray:
        """Where `slide`'s holes truly are on `sample`'s stage, as ``(x, y, radius)`` in
        micrometres: in its place of the mounted holder, through the mount as it truly is (as
        `beads_on_stage`)."""
        holder_name = self.mounted(sample)
        if holder_name is None:
            return np.zeros((3, 0))
        mounted = self.instrument.sample_holder(sample).holders[holder_name]
        at_x, at_y = place_of(mounted.holder, slide.at, "at")
        holes = np.array(
            [[(at_x + x) * 1000.0, (at_y + y) * 1000.0, r * 1000.0] for x, y, r in slide.holes()]
        ).T.reshape(3, -1)
        offset = self.truth.get("mount_offset_um", {})
        if sample in offset:
            offset = offset[sample]
        matrix = holder_to_stage(mounted.mount, (offset.get("x", 0.0), offset.get("y", 0.0)))
        on_stage = matrix[:2, :2] @ holes[:2] + matrix[:2, 3:4]
        return np.stack([on_stage[0], on_stage[1], holes[2]])

    def _opening(
        self, detector: str, state: Mapping[str, Any], answer: Answer
    ) -> np.ndarray | float:
        """How much of the light passing straight through the sample reaches each pixel past an
        opaque slide: all of it inside its holes, none elsewhere, the edge pixels in part. 1 with
        no slide."""
        sample = self.instrument.seen_sample(detector, state)
        slide = self.simulation_of(sample).slide
        if slide is None:
            return 1.0
        to_sample, shift = self._sensor(detector, state, answer)
        width, height = answer.size
        x, y, radius = self.holes_on_stage(slide, sample)
        columns, rows = np.linalg.inv(to_sample) @ np.stack(
            [x - answer.centre[0], y - answer.centre[1]]
        )
        columns = columns + (width - 1) / 2 + shift[0]
        rows = rows + (height - 1) / 2 + shift[1]
        pixel_um = math.hypot(to_sample[0, 0], to_sample[1, 0])
        opening = np.zeros((height, width))
        for column, row, reach in zip(columns, rows, radius / pixel_um):
            left, right = max(int(column - reach) - 1, 0), min(int(column + reach) + 2, width)
            top, bottom = max(int(row - reach) - 1, 0), min(int(row + reach) + 2, height)
            if left >= right or top >= bottom:
                continue
            across = np.arange(left, right) - column
            down = np.arange(top, bottom) - row
            distance = np.hypot(across[np.newaxis, :], down[:, np.newaxis])
            inside = np.clip(reach + 0.5 - distance, 0.0, 1.0)
            opening[top:bottom, left:right] = np.maximum(opening[top:bottom, left:right], inside)
        return opening

    def _slice(
        self, detector: str, state: Mapping[str, Any], answer: Answer, pattern: Pattern
    ) -> np.ndarray:
        """What of the sample lands on each pixel: each bead lit as far as it is, spread as far as
        it is out of focus, and with its light conserved."""
        to_sample, shift = self._sensor(detector, state, answer)
        width, height = answer.size
        field = np.zeros((height, width))
        sample = self.instrument.seen_sample(detector, state)
        y, x, depth = self.beads_on_stage(pattern, sample)

        sample_um = sum(float(state[move.name]) for move in self.instrument.sample_moves(sample))
        lens_um = self._table.focus_um(detector, state)
        lit = np.ones(depth.shape)
        for sheet in answer.sheet_by_source.values():
            plane = sum(float(state[move.name]) for move in self.instrument.sheet_moves(sample))
            lit = lit * np.exp(-2.0 * ((depth + sample_um - plane) / sheet["waist_um"]) ** 2)
        if self.instrument.scanner_of(detector) is not None:
            # A focused spot and what it passes back section the sample: nothing else is lit.
            section = depth_of_field_um(self.instrument, detector, state)
            lit = lit * np.exp(-2.0 * ((depth + sample_um + lens_um) / section) ** 2)

        pixel_um = math.hypot(to_sample[0, 0], to_sample[1, 0])
        grown = pattern.radius / pixel_um
        from_focus = depth + sample_um + lens_um
        per_um = np.where(from_focus >= 0.0, answer.blur_px_per_um, answer.blur_px_per_um_nearer)
        spread = np.hypot(grown, per_um * from_focus)
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
        order = np.argsort(spread)
        columns, rows, spread, brightness = (
            columns[order],
            rows[order],
            spread[order],
            brightness[order],
        )
        painted = np.minimum((2.0 * _REACH_SIGMAS * spread + 2.0) ** 2, float(width * height))
        near = np.cumsum(painted) <= _DRAWN_PIXELS
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
        """Set variables by their full names, such as ``{"stage.x": 10.0}``; and what is on a
        sample, as ``{"stage.simulation": "dye-only"}``."""
        for name, value in values.items():
            sample, _, what = name.partition(".")
            if what == "simulation" and sample in self.simulator.on:
                self.simulator.put(sample, value)
                continue
            if name not in self.state:
                raise KeyError(name)
            self.state[name] = value

    def image(self, detector: str) -> np.ndarray:
        """Take an image with `detector`."""
        return self.simulator.render(detector, self.state)


def problems(instrument: Instrument) -> list[str]:
    """What the simulator cannot draw of `instrument`: a detector timing its photons (FLIM) needs
    the lifetime of every fluorophore it can see."""
    found = []
    for detector in instrument.detectors():
        element = instrument.cubes[detector].element
        if not isinstance(element, PointDetector) or not element.axes:
            continue
        found += [
            f"{detector}: the simulation {name!r} needs its fluorophore's lifetime"
            for sample in instrument.samples_of(detector)
            for name, simulation in instrument.sample_holder(sample).simulations.items()
            if simulation.fluorophore is not None and simulation.fluorophore.lifetime is None
        ]
    return found
