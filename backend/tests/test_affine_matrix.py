"""Tests for fitting and validating the 3D affine matrix from virtual detector images."""

from typing import Generator
import useq as us
import numpy as np
import pytest
from rekuest_next.state.lock import acquired_locks
import copy
from newswitch.broadcasters import FrameBroadcaster
from newswitch.logic.affine_matrix import calculate_3d_affine, check_calibration
from newswitch.managers.virtual import VirtualDetectorManager
from newswitch.managers.virtual.virtual_setup import SceneConfig, VirtualSetup
from newswitch.protocols import CameraState, IlluminationState, StageState
from newswitch.protocols.illumination import Illumination
from newswitch.protocols.objective import ObjectiveState
from newswitch.managers.virtual.virtual_stage import VirtualStageManager


DetectorWithState = tuple[VirtualDetectorManager, VirtualStageManager]


@pytest.fixture
def affine_stage_detector() -> Generator[DetectorWithState, None, None]:
    """Create a complete test setup with detector, IO manager, and all states.

    Uses settings that produce visible images:
        - High illumination intensity (5000.0)
        - Longer exposure (1.0s)
        - Higher gain (10.0)
        - Astigmatism sample type for consistent, visible frames

    Note:
        Camera settings must be set AFTER detector creation because the
        VirtualDetectorManager constructor resets them to config defaults.

    Args:
        tmp_path: Pytest's built-in temporary path fixture.

    Yields:
        A tuple of (VirtualDetectorManager, LocalFileIOManager, IOState, output_dir).
    """
    with acquired_locks("camera_parameters", "stage_position", "io", "objective"):
        # Create states
        camera_state = CameraState()
        stage_state = StageState()
        objective_state = ObjectiveState(slot=1, magnification=10.0, name="10x Air")
        illumination_state = IlluminationState(
            illuminations=[
                Illumination(
                    slot=1,
                    intensity=5000.0,
                    wavelength=488.0,
                    max_intensity=10000.0,
                    is_active=True,
                )
            ],
        )

        stage_manager = VirtualStageManager(stage=stage_state)

        # Create detector with astigmatism sample type for consistent visible frames
        broadcaster = FrameBroadcaster()
        setup = VirtualSetup(
            stage_state=stage_state,
            objective_state=objective_state,
            illumination_state=illumination_state,
            config=SceneConfig(sample_type="astigmatism"),
        )
        detector = VirtualDetectorManager(
            camera_state=camera_state,
            broadcaster=broadcaster,
            frame_source=setup,
        )
        # Activate and configure detector
        detector.activate_detector(1)
        detector.update_detector(slot=1, exposure_time=1.0, gain=10.0)

        yield detector, stage_manager


@pytest.mark.skip(
    reason="Affine matrix calculation test - requires consistent sample and imaging conditions"
)
def test_affine_matrix_calculation(affine_stage_detector: DetectorWithState) -> None:
    """Test that the affine matrix calculation produces a valid matrix.

    This test checks that the calculated affine matrix is a 2x2 matrix with
    reasonable values. It does not check for specific values since the actual
    transformation depends on the sample and imaging conditions.

    Args:
        affine_stage_detector: Fixture providing a configured detector and stage manager.
    """
    detector, stage_manager = affine_stage_detector

    images: list[np.ndarray] = []
    states: list[StageState] = []

    stage_position = [
        us.Position(x=0.0, y=0.0, z=0.0),
        us.Position(x=10.5, y=0.2, z=1.0),
        us.Position(x=21.0, y=0.4, z=2.0),
    ]

    active_detector = detector.activate_detector(1)

    # Simulate capturing images for affine calculation
    for pos in stage_position:
        stage_manager.move(x=pos.x, y=pos.y, z=pos.z)

        frame = detector.capture_image()
        images.append(frame)
        states.append(copy.copy(stage_manager.state))

    # Calculate affine matrix
    affine_matrix = calculate_3d_affine(images, states)

    calibration = check_calibration(
        affine_matrix, objective=detector.frame_source.objective_state, detector=active_detector
    )

    assert calibration.is_valid, f"Affine matrix validation failed: {calibration.warnings}"
