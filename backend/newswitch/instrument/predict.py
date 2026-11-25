"""What a detector will see, from what the compiler found (`newswitch.instrument.compiler`).

`assemble` turns what the tracer found, and the current values, into an `Answer`: where a pixel
looks, how sharp it is, what colour, and how much light.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from newswitch.instrument import tracing
from newswitch.instrument.spec import Instrument


@dataclass(frozen=True)
class Answer:
    """What a detector sees under some state."""

    detector: str
    pixel_to_stage: tuple[tuple[float, float], tuple[float, float]]  # um per pixel, signs included
    centre: tuple[float, float]  # where the middle of the sensor looks, in stage micrometres
    size: tuple[int, int]  # width, height in pixels
    field_of_view_um: tuple[float, float]
    spot_px: float  # rms blur, on the sensor
    relative_illumination: float  # at the corner, against the middle
    distortion_percent: float
    band_nm: float | None  # the mean wavelength arriving, if any arrives
    light: float  # expected counts above the offset, where a bead is
    read_noise_counts: float = 0.0  # what is lost in below this
    light_by_source: Mapping[str, float] = field(default_factory=dict)  # the same, per source
    electrons_by_source: Mapping[str, float] = field(default_factory=dict)  # before the readout
    electrons_by_color: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    """A color camera's: per color, the electrons per source."""
    direct_share_by_source: Mapping[str, float] = field(default_factory=dict)
    """How much of what each source makes arrive came straight through or back, and was not emitted."""
    sheet_by_source: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    """A light sheet's thickness and reach, for each source that makes one."""
    in_focus_px: float = 0.0  # rms blur of what is in focus, on the sensor
    blur_px_per_um: float = 0.0  # what adds to it with the distance from focus, away from the lens
    blur_px_per_um_nearer: float = 0.0  # and towards it

    @property
    def black(self) -> bool:
        """Whether what the detector would see is lost in its noise."""
        return self.light < max(self.read_noise_counts, 1.0)


@dataclass(frozen=True)
class Channel:
    """A source whose light gets through a sample to a detector, with the swaps that decide it: found,
    and never declared."""

    source: str
    detector: str
    electrons: float  # at the source's full power and the detector's exposure, on the reference
    band_nm: float | None  # the mean wavelength arriving
    sample: str  # what it is of
    swaps: Mapping[str, Any]  # the slots that make it: set elsewhere, it is another, or none
    field_um: tuple[float, float]  # what the detector sees of the sample, width and height
    kind: str = ""  # direct (sent straight back or through) or emitted (`compiler.reach`)


@dataclass(frozen=True)
class ChannelRow:
    """A channel as the compiler finds it, for any current values: the swaps that decide it, each
    way of setting them that makes it, and what it is."""

    source: str
    detector: str
    sample: str
    band_nm: float
    deciding: tuple[str, ...]
    ways: tuple[Mapping[str, Any], ...]  # each sets every deciding swap
    kind: str = ""
    dyes: tuple[str, ...] = ()


def state_key(instrument: Instrument, state: Mapping[str, Any]) -> str:
    """Names one combination of what the swaps put in place."""
    swaps = sorted(v.name for v in instrument.variables.values() if v.verb == "swaps")
    return ",".join(f"{name}={state[name]}" for name in swaps)


def _in_the_sheet(
    instrument: Instrument,
    state: Mapping[str, Any],
    arriving: Mapping[str, Any],
    sample: str,
    depth_um: float | None = None,
) -> float:
    """How much of a source's light reaches `sample`: its nearest part, if the sheet missed it."""
    if "sheet" not in arriving:
        return 1.0
    plane = sum(float(state[move.name]) for move in instrument.sheet_moves(sample))
    lit = instrument.lit_um(state, sample=sample, depth_um=depth_um)
    return math.exp(-2.0 * ((lit - plane) / arriving["sheet"]["waist_um"]) ** 2)


def _mounted(
    element: Any,  # noqa: ANN401 - a detector's element
    pixel_x: float,
    pixel_y: float,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """A pixel on the sample, as the way a sensor is mounted turns and mirrors it."""
    pixel_x *= -1.0 if getattr(element, "flip", None) == "x" else 1.0
    pixel_y *= -1.0 if getattr(element, "flip", None) == "y" else 1.0
    rotation = getattr(element, "rotation", None)
    if not rotation:
        return ((pixel_x, 0.0), (0.0, pixel_y))
    cos, sin = math.cos(math.radians(rotation)), math.sin(math.radians(rotation))
    return ((cos * pixel_x, -sin * pixel_y), (sin * pixel_x, cos * pixel_y))


def _share(
    arriving: Mapping[str, Any], area: float, across_x: float, across_y: float, pixels: int
) -> float:
    """How much of a source's light a pixel gets to work with, over an exposure.

    A field shares it by area. A sheet concentrates it into a line, shared along its height. A scan
    gives each pixel all of it, for the pixel's share of the time.
    """
    if "sheet" in arriving and "field_um" in arriving:
        across = across_y if arriving["sheet"]["along"] == "x" else across_x
        return across / arriving["field_um"]
    if "field_um" in arriving:
        return area / (math.pi * (arriving["field_um"] / 2.0) ** 2)
    return 1.0 / pixels


def assemble(
    instrument: Instrument,
    detector: str,
    state: Mapping[str, Any],
    imaging: Mapping[str, float],
    coupling: Mapping[str, Mapping[str, Any]],
    depth_um: float | None = None,
) -> Answer:
    """An `Answer` from what the tracer found and the current values: the light from `coupling`,
    for a sample `depth_um` deep (default: as its holder states)."""
    *_, axis_y, axis_x = instrument.detector_axes(detector)
    binning = state.get(f"{detector}.binning", 1)
    flip = -1.0 if imaging["reflections"] % 2 else 1.0
    magnification = imaging["magnification"]
    pixel_x = axis_x.step * binning / (magnification * flip)
    pixel_y = axis_y.step * binning / magnification
    width, height = axis_x.size // binning, axis_y.size // binning

    sample = instrument.seen_sample(detector, state)
    stage = instrument.cubes[sample]
    centre = [0.0, 0.0]
    for variable in stage.variables.values():
        if variable.verb == "moves" and variable.along in ("x", "y"):
            centre["xy".index(variable.along)] = float(state[variable.name])
    # Where the optics send the image on the sensor: the pixel in its middle looks that far aside.
    mounted = _mounted(instrument.cubes[detector].element, pixel_x, pixel_y)
    aside = (
        imaging.get("shift_x_um", 0.0) / (axis_x.step * binning),
        imaging.get("shift_y_um", 0.0) / (axis_y.step * binning),
    )
    for row in (0, 1):
        centre[row] -= mounted[row][0] * aside[0] + mounted[row][1] * aside[1]

    readout = instrument.cubes[detector].element.readout
    # The pixel a sample point falls on, before any binning: what binning does is the readout's.
    pixel_area = abs(pixel_x * pixel_y) / binning**2
    pixels = axis_x.size * axis_y.size
    binned = binning**2 if readout.binning == "sum" else 1.0
    gain = 10.0 ** (float(state.get(f"{detector}.gain", 0.0)) / 20.0)
    counts_per_electron = gain / readout.electrons_per_count
    exposure = float(state[f"{detector}.exposure"])

    def electrons(source: str, arriving: Mapping[str, Any], per_mw_ms: float) -> float:
        """What a source makes in a pixel, where a bead is."""
        return (
            float(state.get(f"{source}.power", instrument.cubes[source].element.max_power))
            * per_mw_ms
            * exposure
            * _share(arriving, pixel_area, abs(pixel_x) / binning, abs(pixel_y) / binning, pixels)
            * _in_the_sheet(instrument, state, arriving, sample, depth_um)
            * binned
        )

    electrons_by_source = {}
    weighted = 0.0
    for source, arriving in coupling.items():
        amount = electrons(source, arriving, arriving["electrons_per_mw_ms"])
        electrons_by_source[source] = amount
        if arriving["band_mean_nm"] is not None:
            weighted += amount * arriving["band_mean_nm"]
    electrons_by_color: dict[str, dict[str, float]] = {}
    for source, arriving in coupling.items():
        for color, per_mw_ms in arriving.get("colors", {}).items():
            electrons_by_color.setdefault(color, {})[source] = electrons(
                source, arriving, per_mw_ms
            )
    total = sum(electrons_by_source.values())
    band = weighted / total if total > 1e-9 else None

    numerical_aperture = imaging["numerical_aperture"]
    airy_um = 0.61 * (band or 550.0) / 1000.0 / numerical_aperture
    # An Airy disc's rms is about a third of its radius; the geometric spot adds to it.
    spot_um = math.hypot(imaging["spot_center_um"], airy_um / 3.0)
    in_focus_um = math.hypot(imaging.get("in_focus_um", imaging["spot_center_um"]), airy_um / 3.0)
    return Answer(
        detector=detector,
        pixel_to_stage=mounted,
        centre=(centre[0], centre[1]),
        size=(width, height),
        field_of_view_um=(abs(pixel_x) * width, abs(pixel_y) * height),
        spot_px=spot_um / (axis_x.step * binning),
        in_focus_px=in_focus_um / (axis_x.step * binning),
        blur_px_per_um=imaging.get("blur_um_per_um", 0.0) / (axis_x.step * binning),
        blur_px_per_um_nearer=imaging.get(
            "blur_um_per_um_nearer", imaging.get("blur_um_per_um", 0.0)
        )
        / (axis_x.step * binning),
        relative_illumination=imaging["relative_illumination"],
        distortion_percent=imaging["distortion_percent"],
        band_nm=band,
        light=total * counts_per_electron,
        read_noise_counts=readout.read_noise * counts_per_electron,
        light_by_source={s: e * counts_per_electron for s, e in electrons_by_source.items()},
        electrons_by_source=electrons_by_source,
        electrons_by_color=electrons_by_color,
        direct_share_by_source={
            source: arriving.get("direct_share", 0.0) for source, arriving in coupling.items()
        },
        sheet_by_source={
            source: arriving["sheet"]
            for source, arriving in coupling.items()
            if "sheet" in arriving
        },
    )


#: Builds a source's coupling at a detector from what its light goes through: what a sample does.
Couple = Callable[[tracing.Transfer], Mapping[str, Any]]


@dataclass(frozen=True)
class Compiled:
    """What the compiler found for every combination of swaps, on the spectrum `grid`: whatever is
    on the samples (a simulator says that, with `answer`'s ``couple``)."""

    instrument: Instrument
    states: Mapping[str, Mapping[str, Any]]
    grid: np.ndarray = field(default_factory=lambda: np.zeros(0), compare=False, repr=False)
    _rows: list[ChannelRow] = field(default_factory=list, compare=False, repr=False)

    def _reaching(self, state: Mapping[str, Any]) -> dict[tuple[str, str], tuple[Any, ...]]:
        """Which source makes a channel at which detector under `state`: of which sample, of
        which kind and dyes, in which band (`compiler.reach`)."""
        found = {}
        for detector, entry in self.states[state_key(self.instrument, state)].items():
            for source, reach in entry["reach"].items():
                found[source, detector] = (
                    self.instrument.seen_sample(detector, state),
                    reach["kind"],
                    tuple(reach["dyes"]),
                    float(reach["band_nm"]),
                )
        return found

    def channel_rows(self, state: Mapping[str, Any]) -> list[ChannelRow]:
        """Every channel, whatever the swaps say (and whatever `state` sets: the rest).

        A swap decides a channel where setting it otherwise makes the light of its source no longer
        reach its detector, or of another sample, or of another kind or dye: a flip mirror, a
        filter. One that changes only how much arrives, such as an objective, does not: it stays as
        it is.
        """
        if self._rows:
            return self._rows
        swaps = [v for v in self.instrument.variables.values() if v.verb == "swaps"]
        by_key = {state_key(self.instrument, s): s for s in self.instrument.swap_states()}
        reaching = {key: self._reaching(s) for key, s in by_key.items()}

        def apart(one: tuple[Any, ...] | None, other: tuple[Any, ...] | None) -> bool:
            if one is None or other is None:
                return one is not other
            return one[:3] != other[:3]

        rows: list[ChannelRow] = []
        pairs = dict.fromkeys(pair for found in reaching.values() for pair in found)
        for pair in pairs:
            deciding = [
                swap.name
                for swap in swaps
                if any(
                    apart(
                        reaching[key].get(pair),
                        reaching[state_key(self.instrument, {**s, swap.name: slot})].get(pair),
                    )
                    for key, s in by_key.items()
                    for slot in swap.slots
                    if slot != s[swap.name]
                )
            ]
            for key, s in by_key.items():
                found = reaching[key].get(pair)
                if found is None:
                    continue
                sample, kind, dyes, band = found
                way = {name: s[name] for name in deciding}
                row = next(
                    (
                        row
                        for row in rows
                        if (row.source, row.detector, row.sample, row.kind, row.dyes)
                        == (*pair, sample, kind, dyes)
                    ),
                    None,
                )
                if row is None:
                    rows.append(
                        ChannelRow(*pair, sample, band, tuple(deciding), (way,), kind, dyes)
                    )
                elif way not in row.ways:
                    rows[rows.index(row)] = ChannelRow(
                        row.source,
                        row.detector,
                        row.sample,
                        row.band_nm,
                        row.deciding,
                        (*row.ways, way),
                        row.kind,
                        row.dyes,
                    )
        self._rows.extend(rows)
        return self._rows

    def channels(self, state: Mapping[str, Any]) -> list[Channel]:
        """Every channel, set as `state` sets everything but what decides it: each source whose
        light the design says makes one at a detector (`compiler.reach`), and the swaps that make
        it. Its electrons are the reference sample's (`tracing.reference_coupling`), at full
        power: what the optics give, not what a real sample will.

        Of the ways of setting those swaps that make one channel (two filters alike), the one
        nearest `state`.
        """
        found = []
        for row in self.channel_rows(state):
            way = min(row.ways, key=lambda way: sum(state[k] != v for k, v in way.items()))
            under = {**state, **way}
            if self.instrument.sample_of(row.detector, under) != row.sample:
                continue
            element = self.instrument.cubes[row.source].element_at(under)
            answer = self.answer(row.detector, {**under, f"{row.source}.power": element.max_power})
            reach = self.states[state_key(self.instrument, under)][row.detector]["reach"]
            found.append(
                Channel(
                    row.source,
                    row.detector,
                    answer.electrons_by_source.get(row.source, 0.0),
                    reach[row.source]["band_nm"],
                    row.sample,
                    way,
                    answer.field_of_view_um,
                    row.kind,
                )
            )
        return found

    def _moved(self, detector: str, state: Mapping[str, Any]) -> dict[str, float]:
        """What the tracer found for `detector` under the swaps of `state`, with what has moved
        since applied: each move through what the compiler measured it to do, added up."""
        entry = self.states[state_key(self.instrument, state)].get(detector)
        if entry is None:
            raise self.instrument.dark(detector, state)
        imaging = dict(entry["imaging"])
        for name, per_um in entry["moves"].items():
            moved = float(state[name]) - float(self.instrument.variables[name].initial)
            for what in ("magnification", "focus_um", "shift_x_um", "shift_y_um"):
                imaging[what] += per_um[f"{what}_per_um"] * moved
        return imaging

    def focus_um(self, detector: str, state: Mapping[str, Any]) -> float:
        """How far the optics have taken `detector`'s focus from where the sample starts, towards
        the lens: whatever moved it, a lens or the camera."""
        return self._moved(detector, state)["focus_um"]

    def answer(
        self,
        detector: str,
        state: Mapping[str, Any],
        *,
        couple: Couple | None = None,
        depth_um: float | None = None,
    ) -> Answer:
        """What `detector` sees under `state`, from the table: tracing nothing.

        Moves of the optics are not in the table as such: each is applied through the sensitivities
        the compiler measured around the combination of swaps. Where focus is adds up with its
        sign, so one move can undo what another did.

        The light is the reference sample's (`tracing.reference_coupling`), of a sample as deep as
        its holder says; a simulator passes what its sample does (`couple`) and how deep it is.
        """
        imaging = self._moved(detector, state)
        entry = self.states[state_key(self.instrument, state)][detector]
        focus = entry["focus"]
        on = self.instrument.seen_sample(detector, state)
        defocus_um = (
            self.instrument.lit_um(state, imaging["focus_um"], sample=on, depth_um=depth_um)
            + imaging["focus_um"]
        )
        imaging["in_focus_um"] = focus["in_focus_um"]
        imaging["blur_um_per_um"] = focus["blur_um_per_um"]
        imaging["blur_um_per_um_nearer"] = focus["blur_um_per_um_nearer"]
        per_um = focus["blur_um_per_um" if defocus_um >= 0.0 else "blur_um_per_um_nearer"]
        imaging["spot_center_um"] = float(np.hypot(focus["in_focus_um"], per_um * defocus_um))
        coupling = {
            source: (
                couple(found)
                if couple is not None
                else tracing.reference_coupling(found, entry["reach"].get(source), self.grid)
            )
            for source, found in entry["transfer"].items()
        }
        return assemble(self.instrument, detector, state, imaging, coupling, depth_um)
