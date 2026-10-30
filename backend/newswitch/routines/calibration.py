"""Routine for calibrating the affine transformation between stage coordinates and image coordinates."""

import numpy as np

from newswitch import protocols, states
from newswitch.models.devices import Detector
from newswitch.routines.affine_matrix import calibrate_pixel_to_stage
from newswitch.models.calibration import CalibratedLightPath
from newswitch.models.light_path import AffineMatrix
from newswitch.routines.common import field_of_view

#: How far (um) the stage first moves in x and in y to find out the pixel scale.
CALIBRATION_STEP_UM = 20.0
#: How much of the frame the measuring move should shift the image by: long enough for a
#: fraction of a pixel to be a small error, short enough to keep most of the image in common.
SHIFT_OF_FRAME = 1 / 8
#: How many times to try a four times longer move when the first ones do not shift the image.
LONGER_MOVES = 3


def _moves_and_frames(
    stage_manager: protocols.StageManager,
    detector_manager: protocols.DetectorManager,
    slot: int,
    step_x: float,
    step_y: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """An image, one after moving in x only, one after moving in y only; ends where it started."""
    reference = detector_manager.capture_image(slot=slot).data
    stage_manager.move(x=step_x)
    moved_x = detector_manager.capture_image(slot=slot).data
    stage_manager.move(x=-step_x, y=step_y)
    moved_y = detector_manager.capture_image(slot=slot).data
    stage_manager.move(y=-step_y)
    return reference, moved_x, moved_y


def _within_travel(position: float, low: float, high: float, step: float) -> float:
    """`step`, or as much of it as the stage has travel for, in whichever direction has more."""
    above, below = high - position, position - low
    return min(step, above) if above >= below else -min(step, below)


def _measure(
    stage_manager: protocols.StageManager,
    detector_manager: protocols.DetectorManager,
    detector: Detector,
) -> AffineMatrix:
    """The pixel-to-stage affine of `detector`, from moves sized to its pixel scale.

    How long a move has to be depends on the pixel scale, which is what is being measured: a
    first short move finds it out, and a second one, sized to the frame, measures it.

    Raises:
        ValueError: No move shifted the image in a way that tells the pixel scale.
    """
    stage = stage_manager.state

    def measured(step: float) -> AffineMatrix:
        step_x = _within_travel(stage.x, stage.min_x, stage.max_x, step)
        step_y = _within_travel(stage.y, stage.min_y, stage.max_y, step)
        frames = _moves_and_frames(stage_manager, detector_manager, detector.slot, step_x, step_y)
        return calibrate_pixel_to_stage(*frames, step_x, step_y)

    step = CALIBRATION_STEP_UM
    for attempt in range(LONGER_MOVES + 1):
        try:
            first = measured(step)
            break
        except ValueError:
            if attempt == LONGER_MOVES:
                raise
            step *= 4.0
    um_per_px = float(np.hypot(first[0][0], first[1][0]))
    wanted = SHIFT_OF_FRAME * min(detector.width, detector.height) * um_per_px
    # Too short, and a fraction of a pixel is a large error. Too long, and little is left in common.
    return first if 0.5 * wanted <= step <= 2.0 * wanted else measured(wanted)


def calibrate_light_path(
    light_path_manager: protocols.LightPathManager,
    metadata_manager: protocols.MetadataManager,
    calibration_manager: protocols.CalibrationManager,
    stage_manager: protocols.StageManager,
    detector_manager: protocols.DetectorManager,
    detector_state: states.CameraState,
) -> list[CalibratedLightPath]:
    """Calibrate the light path of every active detector: its pixel-to-stage transform.

    The stage moves in x only, then in y only, at a fixed focus, by as much as shifts the image
    by `SHIFT_OF_FRAME`; the image shifts give the pixel scale (rotation and flip included),
    stored per light path for the frames acquired through it. The stage ends where it started.

    Returns:
        The calibrated light paths.
    """

    calibrated_light_paths: list[CalibratedLightPath] = []
    for detector in detector_state.detectors:
        if not detector.is_active:
            continue
        affine_matrix = _measure(stage_manager, detector_manager, detector)

        light_path = light_path_manager.get_light_path_for_detector(detector_slot=detector.slot)
        light_path_state = metadata_manager.get_current_state_for_light_path(light_path)

        fov_width, fov_height = field_of_view(
            detector,
            float(np.hypot(affine_matrix[0][0], affine_matrix[1][0])),
            float(np.hypot(affine_matrix[0][1], affine_matrix[1][1])),
        )

        # Store the calculated affine matrix in the calibration manager's state
        calibrated_light_path = CalibratedLightPath(
            light_path_state_hash=light_path_state.transformation_hash,
            affine_matrix=affine_matrix,
            fov_width=fov_width,
            fov_height=fov_height,
        )
        calibration_manager.set_calibrated_state(calibrated_light_path)
        calibrated_light_paths.append(calibrated_light_path)

    return calibrated_light_paths
