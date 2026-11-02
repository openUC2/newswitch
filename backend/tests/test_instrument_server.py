"""The server running on an instrument: its description is all it needs."""

import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from main_fastapi import create_fastapi_registry
from newswitch.infra.streaming import FrameBroadcaster
from newswitch.microscope.parts import Microscope, build_microscope
from newswitch.instrument import spec
from newswitch.routines.affine_matrix import pixel_shift
from newswitch.routines.calibration import calibrate_light_path
from newswitch.settings import Settings, load_devices, load_settings
from tests.conftest import registry_names, run_settings

BACKEND = Path(__file__).parent.parent
INSTRUMENT = BACKEND / "instruments" / "fake-microscope"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """The settings of a server on the instrument, with its files somewhere temporary."""
    return run_settings(tmp_path, instrument=INSTRUMENT)


@pytest.fixture
def microscope(settings: Settings) -> Microscope:
    """The microscope as the server builds it."""
    return build_microscope(settings, spec.load(INSTRUMENT))


CAMERAS = ("camera_a", "camera_b")


def laser_only(microscope: Microscope) -> None:
    """Fluorescence: bright beads on a dark slide."""
    assert microscope.values is not None
    microscope.values.set({"laser_488.power": 20.0, "led_625.power": 0.0})


def led_only(microscope: Microscope) -> None:
    """Transmitted light: dark beads on a bright field."""
    assert microscope.values is not None
    microscope.values.set({"laser_488.power": 0.0, "led_625.power": 1e-5})  # 10 of its 50 nW


# --- how it is chosen


def test_naming_a_description_runs_that_instrument() -> None:
    """All it takes is the one environment variable."""
    settings = load_settings(str(INSTRUMENT / "microscope.yml"))
    assert settings.instrument == INSTRUMENT / "microscope.yml"


def test_naming_its_folder_does_too() -> None:
    """The folder is the instrument."""
    assert load_settings(str(INSTRUMENT)).instrument == INSTRUMENT


def test_any_other_file_is_refused(tmp_path: Path) -> None:
    """Rather than quietly running something else."""
    path = tmp_path / "newswitch-config.yaml"
    path.write_text("newswitch_version: v1.0.2\ndevices: {}\n")
    with pytest.raises(spec.SpecError, match="does not say"):
        load_settings(str(path))


def test_it_loads_as_the_devices_of_a_server(settings: Settings) -> None:
    """Step 2 of starting up gives the instrument."""
    assert isinstance(load_devices(settings), spec.Instrument)


def test_real_hardware_needs_it_wired(settings: Settings) -> None:
    """The fake microscope's tube lens has no axis left on the board: it says so at start."""
    real = settings.model_copy(update={"simulate": "nothing"})
    with pytest.raises(spec.SpecError, match="tube_a.dz has no wired actuator"):
        build_microscope(real, spec.load(INSTRUMENT))


# --- what it has


def test_it_has_the_parts_its_elements_say() -> None:
    """Which controls exist follows from the description."""
    states, _ = registry_names(spec.load(INSTRUMENT))
    assert {"MoveState", "SwapState", "TuneState", "SourceState", "DetectorState"} <= states
    assert "UC2State" in states  # it describes a board, and simulated that is a virtual one
    assert "UC2State" not in registry_names(spec.load(INSTRUMENT.parent / "cam-test"))[0]


def test_the_models_come_from_the_description(microscope: Microscope) -> None:
    """Sensor sizes off the axes, objectives and filters by their slots, sources by power."""
    first, second = microscope.detector_state.detectors
    assert (first.name, second.name) == ("camera_a", "camera_b")
    assert (first.width, first.height, first.sensor_width) == (512, 512, 512)
    assert first.current_exposure_ms == pytest.approx(100.0)
    swaps = microscope.swap_state.swaps
    assert [lens.label for lens in swaps["objective"]["slot"].options] == [
        "f50 NA 0.1",
        "f25 NA 0.2",
    ]
    assert [f.label for f in swaps["filter_wheel"]["slot"].options] == ["Open", "BP 525/50"]
    sources = microscope.source_state.sources
    assert [source.wavelength for source in sources.values()] == [488.0, 625.0]
    assert sources["laser_488"].power == pytest.approx(20.0)  # of 50 mW
    assert sources["laser_488"].on and not sources["led_625"].on
    assert microscope.move_state.moves["stage"]["x"].maximum == 2000.0


def test_a_source_that_starts_off_comes_on_with_light(microscope: Microscope) -> None:
    """Its switch in the view gives no power, so 0 mW at the start must not stay 0 mW."""
    assert microscope.values is not None and microscope.detector is not None
    led = microscope.source_state.sources["led_625"]
    assert led.lit_power == led.max_power
    microscope.values.set({"laser_488.power": 0.0, led.power_variable: led.lit_power})
    assert microscope.source_state.sources["led_625"].power == led.max_power
    frame = microscope.detector.capture_image("camera_a").data
    assert frame.mean() > 1000
    assert (frame == 65535).mean() < 0.01  # and it is not all white either


def test_the_stage_travels_at_the_speed_it_states(microscope: Microscope) -> None:
    """A jog in the UI is over quickly, instead of the virtual stage's 0.1 s per micrometre."""
    assert microscope.values is not None
    started = time.monotonic()
    microscope.values.set({"stage.x": 100.0}, relative=True)
    assert time.monotonic() - started < 1.0
    assert microscope.values["stage.x"] == pytest.approx(100.0)


def test_a_quick_move_does_not_flood_the_clients(microscope: Microscope) -> None:
    """Every step of a move is a state update for every client: 100 of them left the position
    in the UI seconds behind the stage."""
    assert microscope.values is not None
    steps = []
    task = SimpleNamespace(pausepoint=lambda: None, progress=steps.append)
    microscope.values.set({"stage.x": 100.0}, relative=True, task=task)
    assert len(steps) <= 5  # 0.05 s at its speed, 20 updates a second
    assert microscope.values["stage.x"] == pytest.approx(100.0)


def test_its_objectives_have_a_control() -> None:
    """Which the blok in its description places."""
    ui = spec.load(INSTRUMENT).ui
    assert ui is not None
    assert "<SwapsControl" in ui.bloks["view-fluorescence"].bsx


def test_the_ui_is_the_bloks_it_holds() -> None:
    """A registry with the instrument's bloks, the first its default."""
    registry = create_fastapi_registry(spec.load(INSTRUMENT)).registry
    assert {"move", "calibrate_light_path", "swap", "tune"} <= {
        impl.interface or impl.definition.name for impl in registry.snapshot().get_implementations()
    }
    assert len(registry.registered_bloks) == 4
    assert [name for name, blok in registry.get_declared_bloks().items() if blok.default] == [
        "view-bench"
    ]


# --- what it does


def test_it_takes_images_of_the_sample(microscope: Microscope) -> None:
    """Bright beads on a dark slide, of the sensor's size."""
    assert microscope.detector is not None
    laser_only(microscope)
    frame = microscope.detector.capture_image("camera_a").data
    assert frame.shape == (512, 512)
    assert frame.dtype == np.uint16
    assert np.percentile(frame, 99.9) > 3000 > np.median(frame)


def test_moving_the_stage_moves_the_image(microscope: Microscope) -> None:
    """By the pixel size, as it really is."""
    assert microscope.detector is not None and microscope.values is not None
    laser_only(microscope)
    before = microscope.detector.capture_image("camera_a").data
    microscope.values.set({"stage.x": 100.0}, relative=True)
    after = microscope.detector.capture_image("camera_a").data
    shift = pixel_shift(before, after)
    assert abs(shift[0]) == pytest.approx(100.0 / 5.098, abs=0.3)


def test_each_camera_has_its_own_magnification(microscope: Microscope) -> None:
    """Behind different tube lenses, the same stage move is twice as far on one."""
    assert microscope.detector is not None and microscope.values is not None
    laser_only(microscope)
    a, b = (microscope.detector.capture_image(name).data for name in CAMERAS)
    microscope.values.set({"stage.x": 100.0}, relative=True)
    moved_a, moved_b = (microscope.detector.capture_image(name).data for name in CAMERAS)
    assert abs(pixel_shift(b, moved_b)[0]) == pytest.approx(
        2 * abs(pixel_shift(a, moved_a)[0]), abs=0.5
    )


def test_another_objective_rescales_the_image(microscope: Microscope) -> None:
    """f25 instead of f50: the same stage move is twice as far."""
    assert microscope.detector is not None and microscope.values is not None
    laser_only(microscope)
    microscope.values.set({"objective.slot": 2})
    before = microscope.detector.capture_image("camera_a").data
    microscope.values.set({"stage.x": 50.0}, relative=True)
    after = microscope.detector.capture_image("camera_a").data
    assert abs(pixel_shift(before, after)[0]) == pytest.approx(50.0 / 2.549, abs=0.4)


def test_the_filter_has_a_wedge_the_description_knows_nothing_of(microscope: Microscope) -> None:
    """Swapping it shifts the image."""
    assert microscope.detector is not None and microscope.values is not None
    laser_only(microscope)
    before = microscope.detector.capture_image("camera_a").data
    microscope.values.set({"filter_wheel.slot": 2})
    after = microscope.detector.capture_image("camera_a").data
    assert pixel_shift(before, after) == pytest.approx((3.0, -2.0), abs=0.2)


def test_red_light_through_the_green_filter_is_black(microscope: Microscope) -> None:
    """And with the filter open, it is not."""
    assert microscope.detector is not None and microscope.values is not None
    led_only(microscope)
    assert microscope.detector.capture_image("camera_a").data.mean() > 1000
    microscope.values.set({"filter_wheel.slot": 2})
    assert microscope.detector.capture_image("camera_a").data.mean() < 110


def test_turning_off_all_light_is_black(microscope: Microscope) -> None:
    """Nothing but the camera's offset."""
    assert microscope.detector is not None and microscope.values is not None
    microscope.values.set({"laser_488.power": 0.0, "led_625.power": 0.0})
    assert microscope.detector.capture_image("camera_a").data.mean() < 110


def test_exposure_and_gain_make_it_brighter(microscope: Microscope) -> None:
    """Twice the exposure is twice the light; 6 dB is about the same again."""
    assert microscope.detector is not None and microscope.values is not None
    laser_only(microscope)
    base = np.percentile(microscope.detector.capture_image("camera_a").data, 99.9)
    microscope.values.set({"camera_a.exposure": 200.0, "camera_a.gain": 0.0})
    longer = np.percentile(microscope.detector.capture_image("camera_a").data, 99.9)
    assert longer / base == pytest.approx(2.0, rel=0.1)
    microscope.values.set({"camera_a.exposure": 100.0, "camera_a.gain": 6.0})
    louder = np.percentile(microscope.detector.capture_image("camera_a").data, 99.9)
    assert louder / base == pytest.approx(2.0, rel=0.1)


def test_defocus_blurs_the_image(microscope: Microscope) -> None:
    """Moving the sample out of the focal plane: what an autofocus has to go on."""
    assert microscope.detector is not None and microscope.values is not None
    laser_only(microscope)
    sharp = microscope.detector.capture_image("camera_a").data.astype(float)
    microscope.values.set({"stage.z": 400.0}, relative=True)
    blurred = microscope.detector.capture_image("camera_a").data.astype(float)
    assert np.var(np.diff(blurred, axis=1)) < 0.7 * np.var(np.diff(sharp, axis=1))


def test_binning_and_a_region_work_as_on_any_detector(microscope: Microscope) -> None:
    """Both are read out from the whole sensor by the manager it inherits."""
    assert microscope.detector is not None and microscope.values is not None
    laser_only(microscope)
    microscope.values.set({"camera_a.binning": 2})
    assert microscope.detector.capture_image("camera_a").data.shape == (256, 256)
    microscope.detector.update_detector("camera_a", binning=1, roi=(10, 20, 100, 50))
    assert microscope.detector.capture_image("camera_a").data.shape == (50, 100)


def test_the_live_loop_streams_it(microscope: Microscope) -> None:
    """Frames reach the broadcaster the websocket reads from."""
    assert microscope.detector is not None
    laser_only(microscope)
    broadcaster = FrameBroadcaster()
    import threading

    thread = threading.Thread(target=microscope.detector.acquire_live, args=(broadcaster,))
    microscope.detector_state.is_acquiring = True
    thread.start()
    try:
        deadline = time.monotonic() + 5.0
        while broadcaster.newest("camera_a") is None or broadcaster.newest("camera_b") is None:
            assert time.monotonic() < deadline, "no frames came"
            time.sleep(0.01)
    finally:
        microscope.detector_state.is_acquiring = False
        microscope.detector.close()
        thread.join(timeout=5.0)
    frame = broadcaster.newest("camera_a")
    assert frame is not None and frame.data.shape == (512, 512)


def test_the_real_calibration_finds_what_the_description_does_not_say(
    microscope: Microscope,
) -> None:
    """A 2% scale error, from the button in the UI, for both cameras."""
    assert microscope.values is not None and microscope.detector is not None
    laser_only(microscope)
    paths = calibrate_light_path(
        microscope.optics,
        microscope.metadata,
        microscope.calibration,
        microscope.values,
        microscope.detector,
        microscope.detector_state,
    )
    sizes = [float(np.hypot(p.affine_matrix[0][0], p.affine_matrix[1][0])) for p in paths]
    assert sizes == pytest.approx([5.098, 2.55], rel=0.01)


def test_calibrating_does_not_flip_an_image(microscope: Microscope) -> None:
    """What the design predicts and what calibration measures agree on which way each axis runs,
    mirrored camera included, and on the scale but for the error it is there to find."""
    assert microscope.values is not None and microscope.detector is not None
    laser_only(microscope)

    def scales(name: str) -> np.ndarray:
        path = microscope.optics.get_light_path_for_detector(name)
        matrix = microscope.metadata.get_metadata_for_light_path(path).affine_matrix
        return np.array([matrix[0][0], matrix[1][1]])

    predicted = {name: scales(name) for name in CAMERAS}
    calibrate_light_path(
        microscope.optics,
        microscope.metadata,
        microscope.calibration,
        microscope.values,
        microscope.detector,
        microscope.detector_state,
    )
    for name, nominal in predicted.items():
        assert scales(name) == pytest.approx(nominal, rel=0.03)


def test_an_uncalibrated_image_is_placed_by_what_the_design_predicts(
    microscope: Microscope,
) -> None:
    """Each camera by its own tube lens: the objective alone cannot say."""
    a, b = (
        microscope.metadata.get_metadata_for_light_path(
            microscope.optics.get_light_path_for_detector(name)
        )
        for name in CAMERAS
    )
    assert a.fov_width == pytest.approx(512 * 4.998, rel=0.01)
    assert b.fov_width == pytest.approx(512 * 2.5, rel=0.01)


# --- what the frontend is served


@pytest.mark.parametrize(
    "folder",
    sorted(path.parent for path in (BACKEND / "instruments").glob("*/microscope.yml")),
    ids=lambda path: path.name,
)
def test_every_instruments_bloks_can_be_served(folder: Path) -> None:
    """Checked strictly only here: a refused blok drops the frontend to its built-in view."""
    registry = create_fastapi_registry(spec.load(folder)).registry
    assert registry.snapshot().get_declared_bloks() is not None


def test_a_blok_that_cannot_be_served_is_caught_by_that_check(tmp_path: Path) -> None:
    """A loop over objects with no key passes when a server starts, and fails when it is served."""
    folder = BACKEND / "instruments" / "light-sheet"
    description = (folder / spec.DESCRIPTION).read_text()
    keyed = 'items={camera.axes} let="dim" key={dim.name}'
    assert keyed in description
    path = tmp_path / spec.DESCRIPTION
    path.write_text(description.replace(keyed, 'items={camera.axes} let="dim"'))
    registry = create_fastapi_registry(spec.load(path)).registry
    with pytest.raises(ValueError, match="has no key"):
        registry.snapshot().get_declared_bloks()


def test_the_light_sheet_has_its_own_views() -> None:
    """Its sheet first, then a stack and the stage; none of them a generic one."""
    ui = spec.load(BACKEND / "instruments" / "light-sheet").ui
    assert ui is not None
    assert list(ui.bloks) == ["view-sheet", "view-stack", "view-stage"]
    assert ui.bloks["view-sheet"].default
    sheet = ui.bloks["view-sheet"].bsx
    assert (
        "self.MoveState.moves.stage.z" in sheet and "camera.axes" in sheet and "<LiveView" in sheet
    )
    assert "<AcquisitionControl" in ui.bloks["view-stack"].bsx


def test_the_point_scanner_has_its_own_views() -> None:
    """The scan first, then a stack and the stage; none of them a generic one."""
    ui = spec.load(BACKEND / "instruments" / "point-scanner").ui
    assert ui is not None
    assert list(ui.bloks) == ["view-scan", "view-stack", "view-stage"]
    assert ui.bloks["view-scan"].default
    scan = ui.bloks["view-scan"].bsx
    assert "self.MoveState.moves.stage.z" in scan and "pmt.axes" in scan and "<LiveView" in scan
    assert "<AcquisitionControl" in ui.bloks["view-stack"].bsx
