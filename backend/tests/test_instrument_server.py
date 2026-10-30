"""The server running on an instrument: its description, and no device configuration."""

import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from main import load_devices
from main_fastapi import create_fastapi_registry
from newswitch import config_io
from newswitch.broadcasters import FrameBroadcaster
from newswitch.microscope.parts import Microscope, build_microscope, configured_parts
from newswitch.instrument import spec
from newswitch.routines.affine_matrix import pixel_shift
from newswitch.routines.calibration import calibrate_light_path
from newswitch.settings import Settings, load_settings

BACKEND = Path(__file__).parent.parent
INSTRUMENT = BACKEND / "instruments" / "fake-microscope"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """The settings of a server on the instrument, with its files somewhere temporary."""
    return Settings(
        instrument=INSTRUMENT,
        config_file=None,
        db_path=str(tmp_path / "agent.db"),
        image_dir=tmp_path / "images",
        cache_dir=tmp_path / "cache",
        camera_debug_window=False,
        use_virtual_microscope=True,
    )


@pytest.fixture
def microscope(settings: Settings) -> Microscope:
    """The microscope as the server builds it."""
    return build_microscope(settings, spec.load(INSTRUMENT))


def laser_only(microscope: Microscope) -> None:
    """Fluorescence: bright beads on a dark slide."""
    assert microscope.illumination is not None
    microscope.illumination.turn_on(channel=1, intensity=40.0)
    microscope.illumination.turn_off_channel(2)


def led_only(microscope: Microscope) -> None:
    """Transmitted light: dark beads on a bright field."""
    assert microscope.illumination is not None
    microscope.illumination.turn_off_channel(1)
    microscope.illumination.turn_on(channel=2, intensity=20.0)


# --- how it is chosen


def test_naming_a_description_runs_that_instrument() -> None:
    """All it takes is the one environment variable."""
    settings = load_settings(str(INSTRUMENT / "microscope.yml"))
    assert settings.instrument == INSTRUMENT / "microscope.yml"
    assert settings.config_file is None


def test_naming_its_folder_does_too() -> None:
    """The folder is the instrument."""
    assert load_settings(str(INSTRUMENT)).instrument == INSTRUMENT


def test_a_device_configuration_is_still_one(tmp_path: Path) -> None:
    """Old configurations keep working: a description is told by what it says it is."""
    path = tmp_path / "newswitch-config.yaml"
    path.write_text("newswitch_version: v1.0.2\ndevices: {}\n")
    settings = load_settings(str(path))
    assert settings.instrument is None
    assert settings.static_config_path == path


def test_it_loads_as_the_devices_of_a_server(settings: Settings) -> None:
    """Step 2 of starting up gives the instrument, not a configuration."""
    assert isinstance(load_devices(settings, "ui"), spec.Instrument)


def test_agent_mode_is_refused_for_now(settings: Settings) -> None:
    """It has no agent_ui, and says so rather than failing somewhere later."""
    with pytest.raises(config_io.ConfigError, match="FastAPI mode only"):
        load_devices(settings, "agent_ui")


def test_real_hardware_is_refused_for_now(settings: Settings) -> None:
    """The description does not yet say how an actuator reaches hardware."""
    real = settings.model_copy(update={"use_virtual_microscope": False})
    with pytest.raises(config_io.ConfigError, match="only runs simulated"):
        build_microscope(real, spec.load(INSTRUMENT))


# --- what it has


def test_it_has_the_parts_its_elements_say() -> None:
    """Which controls exist follows from the description."""
    parts = configured_parts(spec.load(INSTRUMENT))
    assert (parts.stage, parts.illumination, parts.detector) == (True, True, True)
    assert (parts.objective, parts.filter_bank, parts.uc2) == (True, True, False)


def test_the_models_come_from_the_description(microscope: Microscope) -> None:
    """Sensor sizes off the axes, objectives and filters by their slots, sources by power."""
    first, second = microscope.camera_state.detectors
    assert (first.name, second.name) == ("camera-a", "camera-b")
    assert (first.width, first.height, first.sensor_width) == (512, 512, 512)
    assert first.current_exposure_time == pytest.approx(0.1)
    assert [lens.name for lens in microscope.objective_state.mounted_lenses] == [
        "f50 NA 0.1",
        "f25 NA 0.2",
    ]
    assert [f.name for f in microscope.filter_bank_state.filters] == ["Open", "BP 525/50"]
    sources = microscope.illumination_state.illuminations
    assert [source.wavelength for source in sources] == [488.0, 625.0]
    assert sources[0].intensity == pytest.approx(40.0)  # 20 of 50 mW
    assert sources[0].is_active and not sources[1].is_active
    assert microscope.stage_state.max_x == 2000.0


def test_a_source_that_starts_off_comes_on_with_light(microscope: Microscope) -> None:
    """Its switch in the view gives no intensity, so 0 mW at the start must not stay 0%."""
    assert microscope.illumination is not None and microscope.detector is not None
    microscope.illumination.turn_off_channel(1)
    microscope.illumination.turn_on(channel=2)
    assert microscope.illumination_state.illuminations[1].intensity == 100.0
    frame = microscope.detector.capture_image(slot=1).data
    assert frame.mean() > 1000
    assert (frame == 65535).mean() < 0.01  # and it is not all white either


def test_the_stage_travels_at_the_speed_it_states(microscope: Microscope) -> None:
    """A jog in the UI is over quickly, instead of the virtual stage's 0.1 s per micrometre."""
    assert microscope.stage is not None
    started = time.monotonic()
    microscope.stage.move(x=100.0)
    assert time.monotonic() - started < 1.0
    assert microscope.stage_state.x == pytest.approx(100.0)


def test_a_quick_move_does_not_flood_the_clients(microscope: Microscope) -> None:
    """Every step of a move is a state update for every client: 100 of them left the position
    in the UI seconds behind the stage."""
    assert microscope.stage is not None
    steps = []
    task = SimpleNamespace(pausepoint=lambda: None, progress=steps.append)
    microscope.stage.move(x=100.0, task=task)
    assert len(steps) <= 5  # 0.2 s at its slowest axis, 20 updates a second
    assert microscope.stage_state.x == pytest.approx(100.0)


def test_rewording_a_comment_does_not_outdate_the_tables(tmp_path: Path) -> None:
    """Only what a description says does."""
    copy = tmp_path / "instrument"
    shutil.copytree(INSTRUMENT, copy)
    description = copy / spec.DESCRIPTION
    description.write_text("# reworded\n" + description.read_text())
    assert spec.load(copy).digest == spec.load(INSTRUMENT).digest


def test_its_objectives_have_a_control() -> None:
    """Which needs naming only here: other views stay as they are."""
    from newswitch.bloks.fluorescence import fluorescence_ui

    assert "self.switch_objective" in fluorescence_ui(True, has_objectives=True)
    assert "self.switch_objective" not in fluorescence_ui(True)


def test_the_ui_is_the_views_it_names() -> None:
    """A registry with the instrument's bloks, the first its default."""
    registry = create_fastapi_registry(spec.load(INSTRUMENT)).registry
    assert {"move_stage", "calibrate_light_path", "switch_objective", "switch_filter"} <= {
        impl.interface or impl.definition.name for impl in registry.snapshot().get_implementations()
    }
    assert len(registry.registered_bloks) == 3


def test_a_view_there_is_none_of_is_refused(tmp_path: Path) -> None:
    """Rather than a server with a missing view."""
    from newswitch.instrument.parts import ui_config

    copy = spec.load(INSTRUMENT)
    with pytest.raises(ValueError, match="no view 'nope'"):
        ui_config(
            spec.Instrument(**{**copy.__dict__, "views": ("nope",)}),  # type: ignore[arg-type]
            "newswitch@1",
        )


def test_the_server_starts_without_the_optics_library() -> None:
    """Only compiling needs it."""
    code = (
        "import sys; from pathlib import Path; from main_fastapi import create_fastapi_registry; "
        "from newswitch.instrument import spec; "
        "create_fastapi_registry(spec.load(Path('instruments/fake-microscope'))); "
        "assert 'optiland' not in sys.modules"
    )
    subprocess.run([sys.executable, "-W", "ignore", "-c", code], check=True, cwd=BACKEND)


# --- what it does


def test_it_takes_images_of_the_sample(microscope: Microscope) -> None:
    """Bright beads on a dark slide, of the sensor's size."""
    assert microscope.detector is not None
    laser_only(microscope)
    frame = microscope.detector.capture_image(slot=1).data
    assert frame.shape == (512, 512)
    assert frame.dtype == np.uint16
    assert np.percentile(frame, 99.9) > 3000 > np.median(frame)


def test_moving_the_stage_moves_the_image(microscope: Microscope) -> None:
    """By the pixel size, as it really is."""
    assert microscope.detector is not None and microscope.stage is not None
    laser_only(microscope)
    before = microscope.detector.capture_image(slot=1).data
    microscope.stage.move(x=100.0)
    after = microscope.detector.capture_image(slot=1).data
    shift = pixel_shift(before, after)
    assert abs(shift[0]) == pytest.approx(100.0 / 5.098, abs=0.3)


def test_each_camera_has_its_own_magnification(microscope: Microscope) -> None:
    """Behind different tube lenses, the same stage move is twice as far on one."""
    assert microscope.detector is not None and microscope.stage is not None
    laser_only(microscope)
    a, b = (microscope.detector.capture_image(slot=slot).data for slot in (1, 2))
    microscope.stage.move(x=100.0)
    moved_a, moved_b = (microscope.detector.capture_image(slot=slot).data for slot in (1, 2))
    assert abs(pixel_shift(b, moved_b)[0]) == pytest.approx(
        2 * abs(pixel_shift(a, moved_a)[0]), abs=0.5
    )


def test_another_objective_rescales_the_image(microscope: Microscope) -> None:
    """f25 instead of f50: the same stage move is twice as far."""
    assert microscope.detector is not None and microscope.stage is not None
    assert microscope.objective is not None
    laser_only(microscope)
    microscope.objective.switch_objective(2)
    before = microscope.detector.capture_image(slot=1).data
    microscope.stage.move(x=50.0)
    after = microscope.detector.capture_image(slot=1).data
    assert abs(pixel_shift(before, after)[0]) == pytest.approx(50.0 / 2.549, abs=0.4)


def test_the_filter_has_a_wedge_the_description_knows_nothing_of(microscope: Microscope) -> None:
    """Swapping it shifts the image."""
    assert microscope.detector is not None and microscope.filter_bank is not None
    laser_only(microscope)
    before = microscope.detector.capture_image(slot=1).data
    microscope.filter_bank.switch_filter(2)
    after = microscope.detector.capture_image(slot=1).data
    assert pixel_shift(before, after) == pytest.approx((3.0, -2.0), abs=0.2)


def test_red_light_through_the_green_filter_is_black(microscope: Microscope) -> None:
    """And with the filter open, it is not."""
    assert microscope.detector is not None and microscope.filter_bank is not None
    led_only(microscope)
    assert microscope.detector.capture_image(slot=1).data.mean() > 1000
    microscope.filter_bank.switch_filter(2)
    assert microscope.detector.capture_image(slot=1).data.mean() < 110


def test_turning_off_all_light_is_black(microscope: Microscope) -> None:
    """Nothing but the camera's offset."""
    assert microscope.detector is not None and microscope.illumination is not None
    microscope.illumination.turn_off_channel(1)
    microscope.illumination.turn_off_channel(2)
    assert microscope.detector.capture_image(slot=1).data.mean() < 110


def test_exposure_and_gain_make_it_brighter(microscope: Microscope) -> None:
    """Twice the exposure is twice the light; 6 dB is about the same again."""
    assert microscope.detector is not None
    laser_only(microscope)
    base = np.percentile(microscope.detector.capture_image(slot=1).data, 99.9)
    microscope.detector.update_detector(1, 0.2, 0.0)
    longer = np.percentile(microscope.detector.capture_image(slot=1).data, 99.9)
    assert longer / base == pytest.approx(2.0, rel=0.1)
    microscope.detector.update_detector(1, 0.1, 6.0)
    louder = np.percentile(microscope.detector.capture_image(slot=1).data, 99.9)
    assert louder / base == pytest.approx(2.0, rel=0.1)


def test_defocus_blurs_the_image(microscope: Microscope) -> None:
    """Moving the sample out of the focal plane: what an autofocus has to go on."""
    assert microscope.detector is not None and microscope.stage is not None
    laser_only(microscope)
    sharp = microscope.detector.capture_image(slot=1).data.astype(float)
    microscope.stage.move(z=400.0)
    blurred = microscope.detector.capture_image(slot=1).data.astype(float)
    assert np.var(np.diff(blurred, axis=1)) < 0.7 * np.var(np.diff(sharp, axis=1))


def test_binning_and_a_region_work_as_on_any_detector(microscope: Microscope) -> None:
    """Both are read out from the whole sensor by the manager it inherits."""
    assert microscope.detector is not None
    laser_only(microscope)
    microscope.detector.update_detector(1, binning=2)
    assert microscope.detector.capture_image(slot=1).data.shape == (256, 256)
    microscope.detector.update_detector(1, binning=1, roi=(10, 20, 100, 50))
    assert microscope.detector.capture_image(slot=1).data.shape == (50, 100)


def test_the_live_loop_streams_it(microscope: Microscope) -> None:
    """Frames reach the broadcaster the websocket reads from."""
    assert microscope.detector is not None
    laser_only(microscope)
    broadcaster = FrameBroadcaster()
    import threading

    thread = threading.Thread(target=microscope.detector.acquire_live, args=(broadcaster,))
    microscope.camera_state.is_acquiring = True
    thread.start()
    try:
        deadline = time.monotonic() + 5.0
        while broadcaster.newest(1) is None or broadcaster.newest(2) is None:
            assert time.monotonic() < deadline, "no frames came"
            time.sleep(0.01)
    finally:
        microscope.camera_state.is_acquiring = False
        microscope.detector.close()
        thread.join(timeout=5.0)
    frame = broadcaster.newest(1)
    assert frame is not None and frame.data.shape == (512, 512)


def test_the_real_calibration_finds_what_the_description_does_not_say(
    microscope: Microscope,
) -> None:
    """A 2% scale error, from the button in the UI, for both cameras."""
    assert microscope.stage is not None and microscope.detector is not None
    laser_only(microscope)
    paths = calibrate_light_path(
        microscope.light_path,
        microscope.metadata,
        microscope.calibration,
        microscope.stage,
        microscope.detector,
        microscope.camera_state,
    )
    sizes = [float(np.hypot(p.affine_matrix[0][0], p.affine_matrix[1][0])) for p in paths]
    assert sizes == pytest.approx([5.098, 2.55], rel=0.01)


def test_calibrating_does_not_flip_an_image(microscope: Microscope) -> None:
    """What the design predicts and what calibration measures agree on which way each axis runs,
    mirrored camera included, and on the scale but for the error it is there to find."""
    assert microscope.stage is not None and microscope.detector is not None
    laser_only(microscope)

    def scales(slot: int) -> np.ndarray:
        path = microscope.light_path.get_light_path_for_detector(slot)
        matrix = microscope.metadata.get_metadata_for_light_path(path).affine_matrix
        return np.array([matrix[0][0], matrix[1][1]])

    predicted = {slot: scales(slot) for slot in (1, 2)}
    calibrate_light_path(
        microscope.light_path,
        microscope.metadata,
        microscope.calibration,
        microscope.stage,
        microscope.detector,
        microscope.camera_state,
    )
    for slot, nominal in predicted.items():
        assert scales(slot) == pytest.approx(nominal, rel=0.03)


def test_an_uncalibrated_image_is_placed_by_what_the_design_predicts(
    microscope: Microscope,
) -> None:
    """Each camera by its own tube lens: the objective alone cannot say."""
    a, b = (
        microscope.metadata.get_metadata_for_light_path(
            microscope.light_path.get_light_path_for_detector(slot)
        )
        for slot in (1, 2)
    )
    assert a.fov_width == pytest.approx(512 * 4.998, rel=0.01)
    assert b.fov_width == pytest.approx(512 * 2.5, rel=0.01)
