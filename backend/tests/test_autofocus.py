"""Unit tests for the software autofocus routine against the simulated microscope."""

import numpy as np
import pytest

from newswitch.microscope.parts import Microscope
from newswitch.routines.autofocus import autofocus_sweep, compute_focus_metric
from newswitch.services.stage import stage_of


def test_compute_focus_metric_prefers_sharp_images() -> None:
    """A sharp checkerboard scores higher than its blurred version."""
    from scipy import ndimage

    rng = np.random.default_rng(42)
    sharp = (rng.random((64, 64)) > 0.5).astype(np.float32) * 255
    blurred = ndimage.gaussian_filter(sharp, sigma=3.0)

    assert compute_focus_metric(sharp) > compute_focus_metric(blurred)
    assert compute_focus_metric(sharp, "intensity_variance") > compute_focus_metric(
        blurred, "intensity_variance"
    )
    with pytest.raises(ValueError):
        compute_focus_metric(sharp, "no_such_metric")


def test_autofocus_sweep_finds_focus_on_simulated_microscope(microscope: Microscope) -> None:
    """The sweep finds the focal plane from a defocused start.

    The reference microscope's description is in focus at z = 0, and defocus blurs its image, so
    the sharpest plane of a sweep around it is that plane. Its first light source is on, so the
    frames carry signal.
    """
    assert microscope.values is not None and microscope.detector is not None
    stage = stage_of(microscope.values, "camera")
    stage.move(z=30.0, is_absolute=True)

    z_positions = [-30.0 + index * 5.0 for index in range(13)]
    best_z, metrics = autofocus_sweep(stage, microscope.detector, z_positions, "camera")

    assert len(metrics) == len(z_positions)
    assert abs(best_z) <= 5.0
    # Sharpness falls off on both sides of focus.
    assert metrics[0] < max(metrics) and metrics[-1] < max(metrics)
