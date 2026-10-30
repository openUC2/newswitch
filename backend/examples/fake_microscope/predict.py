"""What a detector will see, read from the compiled microscope: no optics library needed.

This is the side that runs on the microscope. `assemble` turns what the tracer found, and the current
values, into an `Answer`: where a pixel looks, how sharp it is, what colour, and how much light.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from examples.fake_microscope.spec import Instrument

COMPILED = Path(__file__).parent / "compiled.json"


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

    @property
    def black(self) -> bool:
        """Whether the detector would see next to nothing."""
        return self.light < 1.0


def state_key(instrument: Instrument, state: Mapping[str, Any]) -> str:
    """Names one combination of what the swaps put in place."""
    swaps = sorted(v.name for v in instrument.variables.values() if v.verb == "swaps")
    return ",".join(f"{name}={state[name]}" for name in swaps)


#: Counts per milliwatt-millisecond of light arriving: the fake camera's sensitivity.
COUNTS_PER_LIGHT = 500.0


def assemble(
    instrument: Instrument,
    detector: str,
    state: Mapping[str, Any],
    imaging: Mapping[str, float],
    coupling: Mapping[str, Mapping[str, Any]],
) -> Answer:
    """An `Answer` from what the tracer found and the current values."""
    camera = instrument.cubes[detector]
    axes = camera.element_at(state).properties["axes"]
    binning = state[f"{detector}.binning"]
    flip = -1.0 if imaging["reflections"] % 2 else 1.0
    magnification = imaging["magnification"]
    pixel_x = axes["x"]["pitch"] * binning / (magnification * flip)
    pixel_y = axes["y"]["pitch"] * binning / magnification
    width, height = axes["x"]["size"] // binning, axes["y"]["size"] // binning

    stage = instrument.cubes[instrument.sample_cube()]
    centre = [0.0, 0.0]
    for variable in stage.variables.values():
        if variable.along in ("x", "y"):
            centre["xy".index(variable.along)] = float(state[variable.name])

    light = 0.0
    weighted = 0.0
    for source, arriving in coupling.items():
        power = float(state[f"{source}.power"])
        amount = power * arriving["light_per_mw"]
        light += amount
        if arriving["band_mean_nm"] is not None:
            weighted += amount * arriving["band_mean_nm"]
    band = weighted / light if light > 1e-9 else None
    counts = light * state[f"{detector}.exposure"] * COUNTS_PER_LIGHT * binning**2

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
        spot_px=spot_um / (axes["x"]["pitch"] * binning),
        relative_illumination=imaging["relative_illumination"],
        distortion_percent=imaging["distortion_percent"],
        band_nm=band,
        light=counts,
    )


@dataclass(frozen=True)
class Compiled:
    """What the compiler found for every combination of swaps."""

    instrument: Instrument
    states: Mapping[str, Mapping[str, Any]]
    impacts: list[dict[str, Any]]

    @classmethod
    def load(cls, instrument: Instrument, path: str | Path = COMPILED) -> Compiled:
        """The compiled microscope at `path`."""
        data = json.loads(Path(path).read_text())
        return cls(instrument, data["states"], data["impacts"])

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
