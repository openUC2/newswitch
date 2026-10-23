"""Calibrating a light path measures the pixel scale from two stage moves."""

import pytest

from newswitch.microscope.parts import Microscope
from newswitch.routines.calibration import calibrate_light_path


def test_calibration_measures_the_pixel_scale(microscope: Microscope) -> None:
    """The virtual microscope images 10 px per micrometre at 10x: 0.1 um per pixel.

    The calibration stores what it measures (x is flipped on the virtual camera), and the
    stage ends where it started.
    """
    assert microscope.stage is not None and microscope.detector is not None
    start = (microscope.stage_state.x, microscope.stage_state.y)

    (path,) = calibrate_light_path(
        microscope.light_path,
        microscope.metadata,
        microscope.calibration,
        microscope.stage,
        microscope.detector,
        microscope.camera_state,
    )

    (sx, cxy, _, _), (cyx, sy, _, _) = path.affine_matrix[0], path.affine_matrix[1]
    assert sx == pytest.approx(-0.1, rel=0.2)
    assert sy == pytest.approx(0.1, rel=0.2)
    assert abs(cxy) < 0.25 * abs(sx) and abs(cyx) < 0.5 * abs(sy)
    assert microscope.calibration_state.calibrated_light_paths == [path]
    assert (microscope.stage_state.x, microscope.stage_state.y) == start
