"""A pretend microscope: what the routines would measure, and a camera, for the example to run."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np

from examples.declarative_acquisition.instrument import (
    Instrument,
    Matrix,
    Routine,
    Validity,
    scaling,
    translation,
)

DESCRIPTION = Path(__file__).parent / "microscope.yaml"

#: How the pretend hardware differs from its nominal values: a real microscope is never exact,
#: and the camera is mounted so that x runs the other way.
TRUE_SCALE_ERROR = 1.02


def _magnification(instrument: Instrument, state: Mapping[str, Any]) -> float:
    return instrument.variables["objective.slot"].values[state["objective.slot"]]["magnification"]


def measure_pixel_scale(
    instrument: Instrument, quantity: str, state: Mapping[str, Any]
) -> tuple[Matrix, Validity]:
    """Two stage moves and the image shifts they cause: here, what they would find."""
    pixel_um = instrument.cubes["camera"].properties["pixel_um"]
    size = pixel_um * state["camera.binning"] / _magnification(instrument, state) * TRUE_SCALE_ERROR
    return scaling(-size, size), Validity.MANUAL


def autofocus(
    instrument: Instrument, quantity: str, state: Mapping[str, Any]
) -> tuple[dict[str, float], Validity]:
    """A focus plane: the higher magnification sits closer, the sample is slightly tilted."""
    return (
        {"z0": 40.0 + 2.0 * _magnification(instrument, state), "tilt_x": 0.001, "tilt_y": -0.002},
        Validity.MANUAL,
    )


def home_stage(
    instrument: Instrument, quantity: str, state: Mapping[str, Any]
) -> tuple[None, Validity]:
    """Drive to the end stops: nothing to keep, what counts is that it happened."""
    return None, Validity.VALIDATED


def measure_chromatic_shift(
    instrument: Instrument, quantity: str, state: Mapping[str, Any]
) -> tuple[tuple[float, float, float], Validity]:
    """How far this filter shifts the image from the reference one, in micrometres."""
    return (0.4, -0.2, 0.0), Validity.MANUAL


def measure_field(
    instrument: Instrument, quantity: str, state: Mapping[str, Any]
) -> tuple[str, Validity]:
    """A flat field or a dark frame: a correction image, not a map; here, only its name."""
    return f"{quantity}.zarr", Validity.MANUAL


def register_plate(
    instrument: Instrument, quantity: str, state: Mapping[str, Any]
) -> tuple[Matrix, Validity]:
    """Find the plate on the stage: its corner sits at (1000, 2000) um, turned by nothing."""
    return translation(1000.0, 2000.0), Validity.MANUAL


ROUTINES: Mapping[str, Routine] = {
    "measure_pixel_scale": measure_pixel_scale,
    "autofocus": autofocus,
    "home_stage": home_stage,
    "measure_chromatic_shift": measure_chromatic_shift,
    "measure_flat_field": measure_field,
    "measure_dark": measure_field,
    "register_plate": register_plate,
}


def camera(instrument: Instrument, height: int, width: int) -> np.ndarray:
    """A frame: a spot on a dim, noisy background."""
    rng = np.random.default_rng(1)
    yy, xx = np.mgrid[:height, :width]
    spot = 20000.0 * np.exp(-((xx - width / 2) ** 2 + (yy - height / 2) ** 2) / (2 * 6.0**2))
    return (800.0 + spot + rng.normal(0.0, 20.0, (height, width))).clip(0, 65535).astype(np.uint16)


class Clock:
    """A clock the example can move forward, so that calibrations go stale on demand."""

    def __init__(self) -> None:
        """Start at an arbitrary time."""
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        """The current time, in seconds."""
        return self.now

    def advance(self, hours: float) -> None:
        """Let `hours` pass."""
        self.now += hours * 3600.0


def instrument(clock: Clock | None = None) -> Instrument:
    """The pretend microscope, nothing calibrated."""
    return Instrument.load(DESCRIPTION, ROUTINES, camera, clock or Clock())
