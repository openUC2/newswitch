"""The fake microscope itself: what is really there, and the images it really makes.

The only module that may read `truth.yml`. It traces the same way the compiler does, with the real
errors applied, and adds what the description has no notion of. Everything else has to find those
out from the images, as with a real instrument.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from scipy import ndimage

from examples.fake_microscope import optics
from examples.fake_microscope.predict import COUNTS_PER_LIGHT
from examples.fake_microscope.spec import Instrument

TRUTH = Path(__file__).parent / "truth.yml"

#: The sample: random beads on a slide, and how finely it is rendered.
_SAMPLE_HALF_WIDTH_UM = 1500.0
_SAMPLE_UM_PER_PX = 2.0
_BEADS = 900
_BEAD_RADIUS_UM = 10.0


def _sample() -> np.ndarray:
    """Random beads: random so that a shift between two images has only one answer."""
    size = int(2 * _SAMPLE_HALF_WIDTH_UM / _SAMPLE_UM_PER_PX)
    field = np.zeros((size, size), dtype=np.float32)
    rng = np.random.default_rng(7)
    columns = rng.integers(0, size, _BEADS)
    rows = rng.integers(0, size, _BEADS)
    field[rows, columns] = 1.0
    sigma = _BEAD_RADIUS_UM / _SAMPLE_UM_PER_PX
    blurred = ndimage.gaussian_filter(field, sigma)
    return blurred / blurred.max()


class FakeMicroscope:
    """A microscope you can only learn about by setting it and taking images."""

    def __init__(self, instrument: Instrument, truth_path: Path = TRUTH) -> None:
        """A microscope built as `instrument` says, with the errors in `truth_path`."""
        self.instrument = instrument
        self.truth: dict[str, Any] = yaml.safe_load(Path(truth_path).read_text())
        self.state: dict[str, Any] = instrument.initial_state()
        self._errors = optics.Errors(objective_focal_factor=self.truth["objective_focal_error"])
        self._sample = _sample()
        self._noise = np.random.default_rng(11)

    def set(self, values: Mapping[str, Any]) -> None:
        """Set variables by their full names, such as ``{"stage.x": 10.0}``."""
        for name, value in values.items():
            if name not in self.state:
                raise KeyError(name)
            self.state[name] = value

    def _pixel_to_sample(self, detector: str, imaging: optics.Imaging) -> np.ndarray:
        """Micrometres per pixel, as the camera is really mounted."""
        axes = self.instrument.cubes[detector].element_at(self.state).properties["axes"]
        binning = self.state[f"{detector}.binning"]
        flip = -1.0 if imaging.reflections % 2 else 1.0
        scale = np.diag(
            [
                axes["x"]["pitch"] * binning / (imaging.magnification * flip),
                axes["y"]["pitch"] * binning / imaging.magnification,
            ]
        )
        angle = math.radians(self.truth["camera_rotation_deg"].get(detector, 0.0))
        rotation = np.array(
            [[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]]
        )
        return rotation @ scale

    def image(self, detector: str) -> np.ndarray:
        """Take an image with `detector`, as uint16."""
        state = self.state
        coupling = optics.coupling(self.instrument, detector, state)
        bands = [a["band_mean_nm"] for a in coupling.values() if a["band_mean_nm"] is not None]
        band = bands[0] if bands else 550.0
        imaging = optics.imaging(self.instrument, detector, state, band, self._errors)

        axes = self.instrument.cubes[detector].element_at(state).properties["axes"]
        binning = state[f"{detector}.binning"]
        width, height = axes["x"]["size"] // binning, axes["y"]["size"] // binning
        columns, rows = np.meshgrid(np.arange(width, dtype=float), np.arange(height, dtype=float))

        # the filter's wedge shifts the whole image on the sensor
        wedge = self.truth["filter_wedge_px"]
        if state["filter-wheel.slot"] == wedge["slot"]:
            columns = columns - wedge["shift"][0] / binning
            rows = rows - wedge["shift"][1] / binning
        centred = np.stack([columns - (width - 1) / 2, rows - (height - 1) / 2])
        sample_x, sample_y = np.tensordot(self._pixel_to_sample(detector, imaging), centred, axes=1)
        sample_x = sample_x + state["stage.x"]
        sample_y = sample_y + state["stage.y"]
        to_raster = (self._sample.shape[0] - 1) / 2
        coordinates = np.stack(
            [
                sample_y / _SAMPLE_UM_PER_PX + to_raster,
                sample_x / _SAMPLE_UM_PER_PX + to_raster,
            ]
        )
        beads = ndimage.map_coordinates(self._sample, coordinates, order=1, mode="constant")

        # how much light each source brings: emitted by the beads, or passing around them
        exposure = state[f"{detector}.exposure"]
        counts = np.zeros(beads.shape)
        for source, arriving in coupling.items():
            amount = state[f"{source}.power"] * arriving["light_per_mw"]
            amount = amount * exposure * COUNTS_PER_LIGHT * binning**2
            transmitted = source == "led-625"
            counts = counts + amount * ((1.0 - 0.6 * beads) if transmitted else beads)

        airy_um = 0.61 * band / 1000.0 / imaging.numerical_aperture
        spot_um = math.hypot(imaging.spot_center_um, airy_um / 3.0)
        counts = ndimage.gaussian_filter(counts, spot_um / (axes["x"]["pitch"] * binning))

        radius = np.hypot(centred[0], centred[1]) / np.hypot((width - 1) / 2, (height - 1) / 2)
        counts = counts * (1.0 - (1.0 - imaging.relative_illumination) * radius**2)
        noisy = self._noise.poisson(np.clip(counts, 0, None)) + self._noise.normal(
            100.0, 5.0, counts.shape
        )
        return noisy.clip(0, 65535).astype(np.uint16)
