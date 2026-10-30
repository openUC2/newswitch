"""Calibrating a light path measures the pixel scale from two stage moves."""

from dataclasses import replace

import pytest

from newswitch.microscope.parts import Microscope
from newswitch.models.calibration import CalibratedLightPath
from newswitch.models.light_path import LightPathSnapshot
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


def snapshot(microscope: Microscope, slot: int = 1) -> LightPathSnapshot:
    """The current state of the light path to the detector in `slot`."""
    return microscope.metadata.get_current_state_for_light_path(
        microscope.light_path.get_light_path_for_detector(slot)
    )


def calibrate(microscope: Microscope, scale: float, slot: int = 1) -> CalibratedLightPath:
    """Store a calibration of the scale `scale` for the light path to the detector in `slot`."""
    path = CalibratedLightPath(
        light_path_state_hash=snapshot(microscope, slot).transformation_hash,
        affine_matrix=[
            [scale, 0.0, 0.0, 0.0],
            [0.0, scale, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ],
    )
    microscope.calibration.set_calibrated_state(path)
    return path


def test_a_light_path_has_a_stable_identity(microscope: Microscope) -> None:
    """Both hashes are set, and the same setup gives the same hashes."""
    first, second = snapshot(microscope), snapshot(microscope)
    assert first.hash and first.transformation_hash
    assert (first.hash, first.transformation_hash) == (second.hash, second.transformation_hash)


def test_another_detector_does_not_get_this_detectors_calibration(
    microscope: Microscope,
) -> None:
    """A calibration holds for the detector it was measured with."""
    first = microscope.camera_state.detectors[0]
    microscope.camera_state.detectors.append(replace(first, slot=2, key="second-camera"))
    microscope.light_path.calculate_possible_light_paths()

    calibrate(microscope, 0.5, slot=first.slot)
    with pytest.raises(ValueError, match="No calibrated light path"):
        microscope.calibration_state.get_calibrated_path(snapshot(microscope, 2))


def test_another_objective_does_not_get_this_objectives_calibration(
    microscope: Microscope,
) -> None:
    """Switching the objective changes the scale, so it needs a calibration of its own."""
    assert microscope.objective is not None
    calibrate(microscope, 0.5)
    lenses = microscope.objective_state.mounted_lenses
    assert len(lenses) > 1
    other = next(lens.slot for lens in lenses if lens.slot != microscope.objective_state.slot)
    back = microscope.objective_state.slot

    microscope.objective.switch_objective(other)
    with pytest.raises(ValueError, match="No calibrated light path"):
        microscope.calibration_state.get_calibrated_path(snapshot(microscope))

    microscope.objective.switch_objective(back)
    assert microscope.calibration_state.get_calibrated_path(snapshot(microscope))


def test_recalibrating_replaces_the_calibration(microscope: Microscope) -> None:
    """The newest measurement is the one that applies, not the first."""
    calibrate(microscope, 0.5)
    newest = calibrate(microscope, 0.25)
    assert microscope.calibration_state.calibrated_light_paths == [newest]
    assert microscope.calibration_state.get_calibrated_path(snapshot(microscope)) == newest


def test_where_the_sample_is_and_how_it_is_exposed_do_not_change_the_identity(
    microscope: Microscope,
) -> None:
    """A calibration is found again after moving, refocusing or changing the exposure."""
    assert microscope.stage is not None and microscope.detector is not None
    before = snapshot(microscope)
    microscope.stage.move(x=100.0, y=-50.0, z=20.0)
    microscope.detector.update_detector(1, 0.123, 2.0)
    after = snapshot(microscope)
    assert after.hash == before.hash
    assert after.transformation_hash == before.transformation_hash


def test_a_filter_changes_the_setup_but_not_what_the_optics_do_to_a_pixel(
    microscope: Microscope,
) -> None:
    """The emission filter tells images apart; the calibration of the path still holds."""
    assert microscope.filter_bank is not None
    filters = microscope.filter_bank_state.filters
    assert len(filters) > 1
    before = snapshot(microscope)
    other = next(f.slot for f in filters if f.slot != microscope.filter_bank_state.current_slot)
    microscope.filter_bank.switch_filter(other)
    after = snapshot(microscope)
    assert after.hash != before.hash
    assert after.transformation_hash == before.transformation_hash
