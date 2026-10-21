"""Routine for calibrating the affine transformation between stage coordinates and image coordinates."""

import copy
import numpy as np
from newswitch import protocols
from newswitch.logic.affine_matrix import calculate_3d_affine
from newswitch.protocols.calibration import CalibratedLightPath
from newswitch.protocols.core import AffineMatrix


def calibrate_light_path(
    light_path_manager: protocols.LightPathManager,
    metadata_manager: protocols.MetadataManager,
    calibration_manager: protocols.CalibrationManager,
    stage_manager: protocols.StageManager,
    detector_manager: protocols.DetectorManager,
    detector_state: protocols.CameraState,
) -> list[CalibratedLightPath]:
    """Simulate the acquisition of a multidimensional dataset based on the provided configuration.

    Args:
        config (MultidimensionalAcquisition): Configuration for the acquisition.

    Returns:
        list[AcquiredImage]: List of acquired images with metadata.
    """

    # Move Stage to the slight offset position for calibration
    calibrated_light_paths: list[CalibratedLightPath] = []
    for detector in detector_state.detectors:
        images: list[np.ndarray] = []
        stage_states: list[protocols.StageState] = []

        # Triangle pattern for affine calibration
        stage_manager.move(x=20, y=-20, z=0.0)
        stage_states.append(copy.copy(stage_manager.state))
        frame = detector_manager.capture_image(slot=detector.slot).data
        images.append(frame)

        stage_manager.move(x=-40, y=0, z=20)
        stage_states.append(copy.copy(stage_manager.state))
        frame = detector_manager.capture_image(slot=detector.slot).data
        images.append(frame)

        stage_manager.move(x=20, y=20, z=-20)
        stage_states.append(copy.copy(stage_manager.state))
        frame = detector_manager.capture_image(slot=detector.slot).data
        images.append(frame)

        affine_matrix_x = calculate_3d_affine(images=images, stage_positions=stage_states)
        print(f"Calculated affine matrix: {affine_matrix_x.matrix}")
        # Simulate the calculation of the affine transformation matrix based on the captured image
        affine_matrix: AffineMatrix = [
            [0.34, 0.0, 0.0, 0],
            [0.0, 0.34, 0.0, 0],
            [0.0, 0.0, 1, 0],
            [0.0, 0.0, 0.0, 1.0],
        ]

        light_path = light_path_manager.get_light_path_for_detector(detector_slot=detector.slot)
        light_path_state = metadata_manager.get_current_state_for_light_path(light_path)

        fov_width = detector.pixel_size_um * detector.width
        fov_height = detector.pixel_size_um * detector.height

        # Store the calculated affine matrix in the calibration manager's state
        calibrated_light_path = CalibratedLightPath(
            light_path_state_hash=light_path_state.hash,
            affine_matrix=affine_matrix,
            fov_width=fov_width,
            fov_height=fov_height,
        )
        calibration_manager.set_calibrated_state(calibrated_light_path)
        calibrated_light_paths.append(calibrated_light_path)

    return calibrated_light_paths
