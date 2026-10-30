"""Calibrating a light path measures the pixel scale from two stage moves."""

import math
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
from scipy import ndimage

from newswitch.microscope.parts import Microscope
from newswitch.models.calibration import CalibratedLightPath
from newswitch.models.light_path import LightPathSnapshot
from newswitch.routines.affine_matrix import calibrate_pixel_to_stage, pixel_shift
from newswitch.routines.calibration import calibrate_light_path


def test_calibration_measures_the_pixel_scale(microscope: Microscope) -> None:
    """The virtual microscope images 10 px per micrometre at 10x: 0.1 um per pixel.

    The calibration stores what it measures, and the stage ends where it started. Neither axis is
    flipped: the virtual camera shifts its frame by +10 pixels per micrometre of stage.
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
    assert sx == pytest.approx(0.1, rel=0.02)
    assert sy == pytest.approx(0.1, rel=0.02)
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


# --- measuring: how well, and at which pixel scales


def beads(size: int = 256, seed: int = 3) -> np.ndarray:
    """Random spots, much larger than the frames taken of them, smooth at the pixel scale."""
    rng = np.random.default_rng(seed)
    field = np.zeros((2000, 2000))
    field[rng.integers(0, 2000, 3000), rng.integers(0, 2000, 3000)] = 1.0
    return ndimage.gaussian_filter(field, 4.0)


class Bench:
    """A stage and a camera over `beads`, with a known pixel scale and a turned camera."""

    def __init__(self, um_per_px: float, turn_deg: float = 0.0, limit: float = 5000.0) -> None:
        """A bench seeing `um_per_px` per pixel, mounted `turn_deg` turned."""
        self.sample = beads()
        self.um_per_px = um_per_px
        self.turn = math.radians(turn_deg)
        self.state = SimpleNamespace(
            x=0.0, y=0.0, min_x=-limit, max_x=limit, min_y=-limit, max_y=limit
        )
        self.moves: list[tuple[float, float]] = []
        self.noise = np.random.default_rng(5)

    def move(self, x: float = 0.0, y: float = 0.0, **_: object) -> None:
        """Move the stage by (x, y)."""
        self.state.x += x
        self.state.y += y
        self.moves.append((x, y))

    def capture_image(self, slot: int = 1) -> SimpleNamespace:
        """An image: the sample at the stage position, through the pixel scale."""
        columns, rows = np.meshgrid(np.arange(256.0) - 127.5, np.arange(256.0) - 127.5)
        cos, sin = math.cos(self.turn), math.sin(self.turn)
        x = self.um_per_px * (cos * columns - sin * rows) + self.state.x
        y = self.um_per_px * (sin * columns + cos * rows) + self.state.y
        # the sample's own scale is 1 um per raster pixel
        image = ndimage.map_coordinates(self.sample, [y + 1000.0, x + 1000.0], order=1)
        return SimpleNamespace(
            data=image / image.max() * 1000.0 + self.noise.normal(0.0, 5.0, image.shape)
        )


def calibrated_on(bench: Bench) -> list[list[float]]:
    """Run the real routine on `bench`."""
    detector = SimpleNamespace(slot=1, is_active=True, width=256, height=256)
    light_path = SimpleNamespace(get_light_path_for_detector=lambda detector_slot: "path")
    metadata = SimpleNamespace(
        get_current_state_for_light_path=lambda path: SimpleNamespace(transformation_hash="h")
    )
    calibration = SimpleNamespace(set_calibrated_state=lambda path: None)
    (path,) = calibrate_light_path(
        light_path,  # type: ignore[arg-type]
        metadata,  # type: ignore[arg-type]
        calibration,  # type: ignore[arg-type]
        bench,  # type: ignore[arg-type]
        bench,  # type: ignore[arg-type]
        SimpleNamespace(detectors=[detector]),  # type: ignore[arg-type]
    )
    return path.affine_matrix


@pytest.mark.parametrize("shift", [(0.4, -0.3), (3.5, 2.25), (-17.75, 9.5)])
def test_a_shift_is_found_to_a_fraction_of_a_pixel(shift: tuple[float, float]) -> None:
    """Whole pixels are not enough: a few pixels' move rounded would be many percent off."""
    sample = beads()
    reference = sample[500:756, 500:756]
    moved = ndimage.shift(sample, (shift[1], shift[0]), order=3)[500:756, 500:756]
    assert pixel_shift(reference, moved) == pytest.approx(shift, abs=0.1)


def test_a_shift_is_found_in_a_noisy_image_that_is_smooth_at_the_pixel_scale() -> None:
    """Phase correlation lost this one: all it weighs in the high frequencies is noise."""
    sample = ndimage.gaussian_filter(beads(), 3.0)
    sample = sample / sample.max() * 1000.0
    noise = np.random.default_rng(1)
    reference = sample[500:756, 500:756] + noise.normal(0.0, 10.0, (256, 256))
    moved = sample[502:758, 497:753] + noise.normal(0.0, 10.0, (256, 256))
    # the frame looks 2 down and 3 left, so the content moves up and right
    assert pixel_shift(reference, moved) == pytest.approx((3.0, -2.0), abs=0.2)


def test_what_does_not_move_with_the_sample_does_not_hide_the_shift() -> None:
    """Vignetting stays where it is, and would otherwise vote for no shift at all."""
    sample = beads()
    sample = sample / sample.max() * 1000.0
    yy, xx = np.mgrid[:256, :256]
    vignette = 3000.0 * np.exp(-((xx - 128.0) ** 2 + (yy - 128.0) ** 2) / (2 * 90.0**2))
    reference = sample[500:756, 500:756] + vignette
    moved = sample[505:761, 508:764] + vignette
    assert pixel_shift(reference, moved) == pytest.approx((-8.0, -5.0), abs=0.2)


def test_a_long_shift_is_not_pulled_towards_zero() -> None:
    """A third of the frame: the window would otherwise read it short."""
    sample = beads()
    assert pixel_shift(sample[500:756, 500:756], sample[500:756, 415:671]) == pytest.approx(
        (85.0, 0.0), abs=0.1
    )


@pytest.mark.parametrize("um_per_px", [0.2, 1.0, 5.0])
def test_the_routine_measures_the_pixel_scale_at_any_magnification(um_per_px: float) -> None:
    """At 5 um per pixel a 20 um move is 4 pixels: too few to tell 2%, so the move grows."""
    matrix = calibrated_on(Bench(um_per_px))
    assert math.hypot(matrix[0][0], matrix[1][0]) == pytest.approx(um_per_px, rel=0.005)


def test_the_routine_sees_a_turned_camera_at_low_magnification() -> None:
    """A turn of 1.5 degrees is a tenth of a pixel over 4 pixels: it needs the longer move."""
    matrix = calibrated_on(Bench(5.0, turn_deg=1.5))
    assert math.degrees(math.atan2(matrix[1][0], matrix[0][0])) % 180.0 == pytest.approx(
        1.5, abs=0.1
    )


def test_the_measuring_move_is_sized_to_the_frame() -> None:
    """A short move to find the scale, then one of an eighth of the frame."""
    bench = Bench(5.0)
    calibrated_on(bench)
    assert max(abs(x) for x, _ in bench.moves) == pytest.approx(5.0 * 32.0, rel=0.02)


def test_the_stage_ends_where_it_started() -> None:
    """Whatever the moves were."""
    bench = Bench(5.0)
    calibrated_on(bench)
    assert (bench.state.x, bench.state.y) == pytest.approx((0.0, 0.0))


def test_a_move_stays_within_the_stages_travel() -> None:
    """At an end of its travel, the stage moves the other way."""
    bench = Bench(5.0, limit=100.0)
    bench.state.x = 90.0
    calibrated_on(bench)
    reached = 90.0
    for x, _ in bench.moves:
        reached += x
        assert -100.0 <= reached <= 100.0


def test_a_sample_without_structure_is_refused() -> None:
    """Nothing to measure: better no calibration than a made-up one."""
    flat = np.full((256, 256), 100.0)
    with pytest.raises(ValueError, match="cannot"):
        calibrate_pixel_to_stage(flat, flat, flat, 20.0, 20.0)
