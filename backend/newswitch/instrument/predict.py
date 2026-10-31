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
    light: float  # expected counts at the middle of the image
    light_by_source: Mapping[str, float] = field(default_factory=dict)  # the same, per source
    light_by_color: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    """A color camera's: per color, the light per source."""
    sheet_by_source: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    """A light sheet's thickness and reach, for each source that makes one."""

    @property
    def black(self) -> bool:
        """Whether the detector would see next to nothing."""
        return self.light < 1.0


@dataclass(frozen=True)
class Channel:
    """A source whose light gets through the sample to a detector: found, and never declared."""

    source: str
    detector: str
    light_per_mw: float
    band_nm: float | None  # the mean wavelength arriving


def state_key(instrument: Instrument, state: Mapping[str, Any]) -> str:
    """Names one simulation, and one combination of what the swaps put in place."""
    swaps = sorted(v.name for v in instrument.variables.values() if v.verb == "swaps")
    names = [instrument.simulation_key(), *swaps]
    return ",".join(f"{name}={state[name]}" for name in names)


#: Counts per milliwatt-millisecond of light arriving: the fake camera's sensitivity.
COUNTS_PER_LIGHT = 500.0
#: Light per milliwatt from which a source counts as reaching a detector. A laser's reflection off a
#: slide, past the dichroic, is about 1e-6 (a few counts at full power, under the read noise); the
#: faintest fluorescence described is about 1e-2.
CHANNEL_LIGHT = 1e-4


def _in_the_sheet(
    instrument: Instrument, state: Mapping[str, Any], arriving: Mapping[str, Any]
) -> float:
    """How much of a source's light a flat sample still gets, having moved along the axis."""
    if "sheet" not in arriving:
        return 1.0
    moved = sum(
        float(state[variable.name]) - float(variable.initial)
        for variable in instrument.cubes[instrument.sample_cube()].variables.values()
        if variable.verb == "moves" and variable.along == "axis"
    )
    return math.exp(-2.0 * (moved / arriving["sheet"]["waist_um"]) ** 2)


def assemble(
    instrument: Instrument,
    detector: str,
    state: Mapping[str, Any],
    imaging: Mapping[str, float],
    coupling: Mapping[str, Mapping[str, Any]],
) -> Answer:
    """An `Answer` from what the tracer found and the current values."""
    *_, axis_y, axis_x = instrument.detector_axes(detector)
    binning = state[f"{detector}.binning"]
    flip = -1.0 if imaging["reflections"] % 2 else 1.0
    magnification = imaging["magnification"]
    pixel_x = axis_x.step * binning / (magnification * flip)
    pixel_y = axis_y.step * binning / magnification
    width, height = axis_x.size // binning, axis_y.size // binning

    stage = instrument.cubes[instrument.sample_cube()]
    centre = [0.0, 0.0]
    for variable in stage.variables.values():
        if variable.verb == "moves" and variable.along in ("x", "y"):
            centre["xy".index(variable.along)] = float(state[variable.name])

    # Binned pixels are averaged, not summed (`VirtualDetectorManager._read_out`): binning does
    # not change the counts.
    gain = 10.0 ** (float(state.get(f"{detector}.gain", 0.0)) / 20.0)
    per_mw = state[f"{detector}.exposure"] * COUNTS_PER_LIGHT * gain
    counts_by_source = {}
    weighted = 0.0
    for source, arriving in coupling.items():
        amount = (
            float(state[f"{source}.power"])
            * arriving["light_per_mw"]
            * _in_the_sheet(instrument, state, arriving)
        )
        counts_by_source[source] = amount * per_mw
        if arriving["band_mean_nm"] is not None:
            weighted += amount * arriving["band_mean_nm"]
    counts_by_color: dict[str, dict[str, float]] = {}
    for source, arriving in coupling.items():
        for color, light_per_mw in arriving.get("colors", {}).items():
            amount = (
                float(state[f"{source}.power"])
                * light_per_mw
                * _in_the_sheet(instrument, state, arriving)
            )
            counts_by_color.setdefault(color, {})[source] = amount * per_mw
    total = sum(counts_by_source.values())
    band = weighted * per_mw / total if total > 1e-9 else None

    numerical_aperture = imaging["numerical_aperture"]
    airy_um = 0.61 * (band or 550.0) / 1000.0 / numerical_aperture
    # An Airy disc's rms is about a third of its radius; the geometric spot adds to it.
    spot_um = math.hypot(imaging["spot_center_um"], airy_um / 3.0)
    return Answer(
        detector=detector,
        pixel_to_stage=((pixel_x, 0.0), (0.0, pixel_y)),
        centre=(centre[0], centre[1]),
        size=(width, height),
        field_of_view_um=(abs(pixel_x) * width, abs(pixel_y) * height),
        spot_px=spot_um / (axis_x.step * binning),
        relative_illumination=imaging["relative_illumination"],
        distortion_percent=imaging["distortion_percent"],
        band_nm=band,
        light=total,
        light_by_source=counts_by_source,
        light_by_color=counts_by_color,
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

    def channels(self, state: Mapping[str, Any]) -> list[Channel]:
        """Which source reaches which detector under `state`, from the table."""
        return [
            Channel(source, detector, arriving["light_per_mw"], arriving["band_mean_nm"])
            for detector, entry in self.states[state_key(self.instrument, state)].items()
            for source, arriving in entry["coupling"].items()
            if arriving["light_per_mw"] >= CHANNEL_LIGHT
        ]

    def answer(self, detector: str, state: Mapping[str, Any]) -> Answer:
        """What `detector` sees under `state`, from the table: tracing nothing.

        Moves along the optical axis are not in the table as such: each is applied through the
        sensitivities the compiler measured around the combination of swaps.
        """
        entry = self.states[state_key(self.instrument, state)][detector]
        imaging = dict(entry["imaging"])
        blur_squared = imaging["spot_center_um"] ** 2
        for name, sensitivity in entry["axial"].items():
            moved = float(state[name]) - float(self.instrument.variables[name].initial)
            imaging["magnification"] += sensitivity["magnification_per_um"] * moved
            blur_squared += (sensitivity["blur_um_per_um"] * moved) ** 2
        imaging["spot_center_um"] = float(np.sqrt(blur_squared))
        return assemble(self.instrument, detector, state, imaging, entry["coupling"])
