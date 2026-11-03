"""What a detector will see, from what the compiler found (`newswitch.instrument.compiler`).

`assemble` turns what the tracer found, and the current values, into an `Answer`: where a pixel
looks, how sharp it is, what colour, and how much light.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np

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
    blur_px_per_um: float = 0.0  # what adds to it with the distance from focus

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
    electrons: float  # at the source's full power, and the detector's exposure
    band_nm: float | None  # the mean wavelength arriving
    sample: str  # what it is of
    swaps: Mapping[str, Any]  # the slots that make it: set elsewhere, it is another, or none
    field_um: tuple[float, float]  # what the detector sees of the sample, width and height


#: How far apart two bands are before they are two channels, in nanometres.
BAND_APART_NM = 1.0


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


def state_key(instrument: Instrument, state: Mapping[str, Any]) -> str:
    """Names what is on every sample, and one combination of what the swaps put in place."""
    swaps = sorted(v.name for v in instrument.variables.values() if v.verb == "swaps")
    names = [*instrument.simulation_keys(), *swaps]
    return ",".join(f"{name}={state[name]}" for name in names)


def _in_the_sheet(
    instrument: Instrument, state: Mapping[str, Any], arriving: Mapping[str, Any], sample: str
) -> float:
    """How much of a source's light reaches `sample`: its nearest part, if the sheet missed it."""
    if "sheet" not in arriving:
        return 1.0
    plane = sum(float(state[move.name]) for move in instrument.sheet_moves(sample))
    lit = instrument.lit_um(state, sample=sample)
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
) -> Answer:
    """An `Answer` from what the tracer found and the current values."""
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
            * _in_the_sheet(instrument, state, arriving, sample)
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
        pixel_to_stage=_mounted(instrument.cubes[detector].element, pixel_x, pixel_y),
        centre=(centre[0], centre[1]),
        size=(width, height),
        field_of_view_um=(abs(pixel_x) * width, abs(pixel_y) * height),
        spot_px=spot_um / (axis_x.step * binning),
        in_focus_px=in_focus_um / (axis_x.step * binning),
        blur_px_per_um=imaging.get("blur_um_per_um", 0.0) / (axis_x.step * binning),
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


@dataclass(frozen=True)
class Compiled:
    """What the compiler found for every simulation and combination of swaps."""

    instrument: Instrument
    states: Mapping[str, Mapping[str, Any]]
    _rows: dict[tuple[Any, ...], list[ChannelRow]] = field(
        default_factory=dict, compare=False, repr=False
    )

    def _reaching(self, state: Mapping[str, Any]) -> dict[tuple[str, str], tuple[str, float]]:
        """Which source reaches which detector under `state`, more than its noise at full power:
        of which sample, in which band."""
        found = {}
        for detector, entry in self.states[state_key(self.instrument, state)].items():
            readout = self.instrument.cubes[detector].element.readout
            for source, arriving in entry["coupling"].items():
                element = self.instrument.cubes[source].element_at(state)
                answer = self.answer(detector, {**state, f"{source}.power": element.max_power})
                band = arriving["band_mean_nm"]
                if band is not None and answer.electrons_by_source[source] > max(
                    3.0 * readout.read_noise, 1.0
                ):
                    found[source, detector] = (
                        self.instrument.seen_sample(detector, state),
                        float(band),
                    )
        return found

    def channel_rows(self, state: Mapping[str, Any]) -> list[ChannelRow]:
        """Every channel of the simulations in `state`, whatever the swaps say.

        A swap decides a channel where setting it otherwise makes the light of its source no longer
        reach its detector, or of another sample, or in another band: a flip mirror, a filter. One
        that changes only how much arrives, such as an objective, does not: it stays as it is.
        """
        simulations = tuple(state[key] for key in self.instrument.simulation_keys())
        if simulations in self._rows:
            return self._rows[simulations]
        swaps = [v for v in self.instrument.variables.values() if v.verb == "swaps"]
        states = [
            s
            for s in self.instrument.swap_states()
            if tuple(s[key] for key in self.instrument.simulation_keys()) == simulations
        ]
        by_key = {state_key(self.instrument, s): s for s in states}
        reaching = {key: self._reaching(s) for key, s in by_key.items()}

        def apart(one: tuple[str, float] | None, other: tuple[str, float] | None) -> bool:
            if one is None or other is None:
                return one is not other
            return one[0] != other[0] or abs(one[1] - other[1]) >= BAND_APART_NM

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
                way = {name: s[name] for name in deciding}
                row = next(
                    (
                        row
                        for row in rows
                        if (row.source, row.detector, row.sample) == (*pair, found[0])
                        and abs(row.band_nm - found[1]) < BAND_APART_NM
                    ),
                    None,
                )
                if row is None:
                    rows.append(ChannelRow(*pair, found[0], found[1], tuple(deciding), (way,)))
                elif way not in row.ways:
                    rows[rows.index(row)] = ChannelRow(
                        row.source,
                        row.detector,
                        row.sample,
                        row.band_nm,
                        row.deciding,
                        (*row.ways, way),
                    )
        self._rows[simulations] = rows
        return rows

    def channels(self, state: Mapping[str, Any]) -> list[Channel]:
        """Every channel, set as `state` sets everything but what decides it: each source whose light
        gets to a detector more than its noise, at full power, and the swaps that make it do.

        Of the ways of setting those swaps that make one channel (two filters alike), the one
        nearest `state`.
        """
        found = []
        for row in self.channel_rows(state):
            way = min(row.ways, key=lambda way: sum(state[k] != v for k, v in way.items()))
            under = {**state, **way}
            if self.instrument.sample_of(row.detector, under) != row.sample:
                continue
            readout = self.instrument.cubes[row.detector].element.readout
            element = self.instrument.cubes[row.source].element_at(under)
            answer = self.answer(row.detector, {**under, f"{row.source}.power": element.max_power})
            electrons = answer.electrons_by_source.get(row.source, 0.0)
            if electrons > max(3.0 * readout.read_noise, 1.0):
                found.append(
                    Channel(
                        row.source,
                        row.detector,
                        electrons,
                        self.states[state_key(self.instrument, under)][row.detector]["coupling"][
                            row.source
                        ]["band_mean_nm"],
                        row.sample,
                        way,
                        answer.field_of_view_um,
                    )
                )
        return found

    def answer(self, detector: str, state: Mapping[str, Any]) -> Answer:
        """What `detector` sees under `state`, from the table: tracing nothing.

        Moves along the optical axis are not in the table as such: each is applied through the
        sensitivities the compiler measured around the combination of swaps.
        """
        entry = self.states[state_key(self.instrument, state)].get(detector)
        if entry is None:
            raise self.instrument.dark(detector, state)
        imaging = dict(entry["imaging"])
        focus = entry["focus"]
        blur_squared = focus["in_focus_um"] ** 2
        for name, sensitivity in entry["axial"].items():
            moved = float(state[name]) - float(self.instrument.variables[name].initial)
            imaging["magnification"] += sensitivity["magnification_per_um"] * moved
            if name not in focus["moves"]:
                blur_squared += (sensitivity["blur_um_per_um"] * moved) ** 2
        on = self.instrument.seen_sample(detector, state)
        sample = {move.name for move in self.instrument.sample_moves(on)}
        lens_um = sum(float(state[name]) for name in focus["moves"] if name not in sample)
        defocus_um = self.instrument.lit_um(state, lens_um, sample=on) + lens_um
        imaging["in_focus_um"] = float(np.sqrt(blur_squared))
        imaging["blur_um_per_um"] = focus["blur_um_per_um"]
        imaging["spot_center_um"] = float(
            np.sqrt(blur_squared + (focus["blur_um_per_um"] * defocus_um) ** 2)
        )
        return assemble(self.instrument, detector, state, imaging, entry["coupling"])
