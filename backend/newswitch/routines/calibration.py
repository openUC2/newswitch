"""Routine for calibrating the affine transformation between stage coordinates and image coordinates."""

import numpy as np

from newswitch import protocols, states
from newswitch.routines.affine_matrix import calibrate_pixel_to_stage
from newswitch.models.calibration import CalibratedLightPath
from newswitch.models.light_path import AffineMatrix
from newswitch.routines.common import field_of_view

#: How far (um) the stage moves in x and in y to measure the pixel scale.
CALIBRATION_STEP_UM = 20.0


def calibrate_light_path(
    light_path_manager: protocols.LightPathManager,
    metadata_manager: protocols.MetadataManager,
    calibration_manager: protocols.CalibrationManager,
    stage_manager: protocols.StageManager,
    detector_manager: protocols.DetectorManager,
    detector_state: states.CameraState,
) -> list[CalibratedLightPath]:
    """Calibrate the light path of every active detector: its pixel-to-stage transform.

    The stage moves `CALIBRATION_STEP_UM` in x only, then in y only, at a fixed focus; the
    image shifts give the pixel scale (rotation and flip included), stored per light path
    for the frames acquired through it. The stage ends where it started.

    Returns:
        The calibrated light paths.
    """

    calibrated_light_paths: list[CalibratedLightPath] = []
    for detector in detector_state.detectors:
        if not detector.is_active:
            continue
        # Two moves at a fixed focus: x only, then y only, each from the reference spot
        reference = detector_manager.capture_image(slot=detector.slot).data
        stage_manager.move(x=CALIBRATION_STEP_UM)
        moved_x = detector_manager.capture_image(slot=detector.slot).data
        stage_manager.move(x=-CALIBRATION_STEP_UM, y=CALIBRATION_STEP_UM)
        moved_y = detector_manager.capture_image(slot=detector.slot).data
        stage_manager.move(y=-CALIBRATION_STEP_UM)

        affine_matrix: AffineMatrix = calibrate_pixel_to_stage(
            reference, moved_x, moved_y, CALIBRATION_STEP_UM, CALIBRATION_STEP_UM
        )

        light_path = light_path_manager.get_light_path_for_detector(detector_slot=detector.slot)
        light_path_state = metadata_manager.get_current_state_for_light_path(light_path)

        fov_width, fov_height = field_of_view(
            detector,
            float(np.hypot(affine_matrix[0][0], affine_matrix[1][0])),
            float(np.hypot(affine_matrix[0][1], affine_matrix[1][1])),
        )

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
