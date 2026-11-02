"""Routine for calibrating the affine transformation between stage coordinates and image coordinates."""

import numpy as np

from newswitch import protocols, states
from newswitch.models.devices import Detector
from newswitch.routines.affine_matrix import calibrate_pixel_to_stage
from newswitch.models.calibration import CalibratedLightPath
from newswitch.models.light_path import AffineMatrix
from newswitch.services.stage import Stage, stage_of
from newswitch.services.values import Values

#: How much of the frame the measuring move should shift the image by: long enough for a
#: fraction of a pixel to be a small error, short enough to keep most of the image in common.
SHIFT_OF_FRAME = 1 / 8
#: How long to try a first move, against the one that would shift the image by `SHIFT_OF_FRAME` as
#: predicted. Short ones first: too short shifts nothing and says so, too long reads noise as a shift.
TRIES = (1 / 4, 1 / 16, 1.0, 1 / 64, 4.0, 16.0)
#: How far apart, as a share of a pixel's size, two measurements of it may be and still be believed.
AGREEMENT = 0.05


def _moves_and_frames(
    stage_manager: Stage,
    detector_manager: protocols.DetectorManager,
    name: str,
    step_x: float,
    step_y: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """An image, one after moving in x only, one after moving in y only; ends where it started."""
    reference = detector_manager.capture_image(name).data
    stage_manager.move(x=step_x)
    moved_x = detector_manager.capture_image(name).data
    stage_manager.move(x=-step_x, y=step_y)
    moved_y = detector_manager.capture_image(name).data
    stage_manager.move(y=-step_y)
    return reference, moved_x, moved_y


def _within_travel(position: float, low: float, high: float, step: float) -> float:
    """`step`, or as much of it as the stage has travel for, in whichever direction has more."""
    above, below = high - position, position - low
    return min(step, above) if above >= below else -min(step, below)


def _measure(
    stage_manager: Stage,
    detector_manager: protocols.DetectorManager,
    detector: Detector,
    predicted_um_per_px: float,
) -> AffineMatrix:
    """The pixel-to-stage affine of `detector`, from moves sized to its pixel scale.

    How long a move has to be depends on the pixel scale, which is what is being measured: a first
    move, sized by what the optics predict, finds it out, and a second one, sized to the frame,
    measures it. Only if the two agree is that believed, as a sample with too little structure can
    shift the wrong way by any amount.

    Raises:
        ValueError: No move shifted the image in a way that tells the pixel scale.
    """
    stage = stage_manager.state

    def measured(step: float) -> np.ndarray:
        step_x = _within_travel(stage.x, stage.min_x, stage.max_x, step)
        step_y = _within_travel(stage.y, stage.min_y, stage.max_y, step)
        frames = _moves_and_frames(stage_manager, detector_manager, detector.name, step_x, step_y)
        return np.array(calibrate_pixel_to_stage(*frames, step_x, step_y))

    def sized(um_per_px: float) -> float:
        return SHIFT_OF_FRAME * min(detector.plane()) * um_per_px

    problem = "the moves did not agree on it"
    for share in TRIES:
        try:
            first = measured(sized(predicted_um_per_px) * share)
            um_per_px = float(np.hypot(first[0][0], first[1][0]))
            second = measured(sized(um_per_px))
        except ValueError as error:
            problem = str(error)
            continue
        if np.abs(second - first).max() <= AGREEMENT * um_per_px:
            return second.tolist()
    raise ValueError(f"The pixel scale of {detector.name} cannot be determined: {problem}")


def calibrate_light_path(
    optics_manager: protocols.OpticsManager,
    metadata_manager: protocols.MetadataManager,
    calibration_manager: protocols.CalibrationManager,
    values: Values,
    detector_manager: protocols.DetectorManager,
    detector_state: states.DetectorState,
) -> list[CalibratedLightPath]:
    """Calibrate the light path of every active detector: its pixel-to-stage transform.

    The stage moves in x only, then in y only, at a fixed focus, by as much as shifts the image
    by `SHIFT_OF_FRAME`; the image shifts give the pixel scale (rotation and flip included),
    stored per light path for the frames acquired through it. The stage ends where it started.

    Returns:
        The calibrated light paths.

    Raises:
        ValueError: A detector could not be calibrated; the others are, and it says which.
    """

    calibrated_light_paths: list[CalibratedLightPath] = []
    problems: list[str] = []
    for detector in detector_state.detectors:
        if not detector.is_active:
            continue
        light_path = optics_manager.get_light_path_for_detector(detector.name)
        light_path_state = metadata_manager.get_current_state_for_light_path(light_path)
        known = metadata_manager.get_metadata_for_light_path(light_path).affine_matrix
        try:
            affine_matrix = _measure(
                stage_of(values, detector.name),
                detector_manager,
                detector,
                float(np.hypot(known[0][0], known[1][0])),
            )
        except ValueError as error:
            # What one detector cannot see under this light is no reason to lose the others.
            problems.append(str(error))
            continue

        calibrated_light_path = CalibratedLightPath(
            key=light_path_state.key, affine_matrix=affine_matrix
        )
        calibration_manager.set_calibrated_state(calibrated_light_path)
        calibrated_light_paths.append(calibrated_light_path)

    if problems:
        raise ValueError(
            "; ".join(problems) + f" ({len(calibrated_light_paths)} calibrated all the same)"
        )
    return calibrated_light_paths
