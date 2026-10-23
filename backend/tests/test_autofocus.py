"""Unit tests for the software autofocus routine against the virtual microscope."""

import numpy as np
import pytest

from newswitch.microscope.parts import Microscope
from newswitch.routines.autofocus import autofocus_sweep, compute_focus_metric


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


def test_autofocus_sweep_finds_focus_on_virtual_microscope(microscope: Microscope) -> None:
    """The sweep finds the virtual detector's focal plane from a defocused start.

    The virtual detector blurs a frame with a Gaussian of sigma = 0.5 px per micrometre of
    distance to its focal plane, so the sharpest plane of a sweep around it is that plane.
    The reference microscope's first light source is on, so the frames carry signal; the
    focal plane sits inside the stage's travel (z starts at 0).
    """
    assert microscope.stage is not None and microscope.detector is not None
    microscope.detector.config.focal_plane_z = 50.0
    microscope.stage.move(z=56.0, is_absolute=True)

    z_positions = [44.0 + index * 1.0 for index in range(13)]
    best_z, metrics = autofocus_sweep(
        microscope.stage, microscope.detector, z_positions, detector_slot=1
    )

    assert len(metrics) == len(z_positions)
    assert abs(best_z - 50.0) <= 1.0
    # Sharpness falls off on both sides of focus.
    assert metrics[0] < max(metrics) and metrics[-1] < max(metrics)
