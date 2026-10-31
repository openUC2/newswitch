"""Tests for fitting and validating the 3D affine matrix from a detector's rendered images."""

from types import SimpleNamespace

import numpy as np
import pytest
import useq as us

from newswitch.microscope.parts import Microscope
from newswitch.routines.affine_matrix import calculate_3d_affine, check_calibration


@pytest.mark.skip(
    reason="Affine matrix calculation test - requires consistent sample and imaging conditions"
)
def test_affine_matrix_calculation(microscope: Microscope) -> None:
    """Test that the affine matrix calculation produces a valid matrix.

    This test checks that the calculated affine matrix is a 2x2 matrix with
    reasonable values. It does not check for specific values since the actual
    transformation depends on the sample and imaging conditions.

    Uses settings that produce visible images: half of the laser's power, a longer exposure (1 s)
    and a higher gain (10 dB).

    Args:
        microscope: The reference microscope.
    """
    assert microscope.detector is not None and microscope.values is not None
    values = microscope.values
    values.set({"laser_488.power": 25.0, "camera.exposure": 1000.0, "camera.gain": 10.0})

    images: list[np.ndarray] = []
    states: list[SimpleNamespace] = []

    stage_position = [
        us.Position(x=0.0, y=0.0, z=0.0),
        us.Position(x=10.5, y=0.2, z=1.0),
        us.Position(x=21.0, y=0.4, z=2.0),
    ]

    microscope.detector.activate_detector("camera")

    # Capture images for affine calculation
    for pos in stage_position:
        values.set({"stage.x": pos.x, "stage.y": pos.y, "stage.z": pos.z}, relative=True)

        frame = microscope.detector.capture_image().data
        images.append(frame)
        states.append(
            SimpleNamespace(x=values["stage.x"], y=values["stage.y"], z=values["stage.z"])
        )

    # Calculate affine matrix
    affine_matrix = calculate_3d_affine(images, states)

    predicted = microscope.optics_state.detectors["camera"].pixel_um
    calibration = check_calibration(affine_matrix, predicted_um_per_px=predicted)

    assert calibration.is_valid, f"Affine matrix validation failed: {calibration.warnings}"
