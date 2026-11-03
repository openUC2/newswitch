"""Tests for the translation between config dataclasses and manager dataclasses."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

import pytest
from rekuest_next.state.lock import acquired_locks

from newswitch.config_io import (
    AxisConfig,
    ConfigError,
    DetectorConfig,
    FilterConfig,
    adapters,
    load_config,
)
from newswitch.config_io import ObjectiveConfig as ObjectiveDevice
from newswitch.config_io.devices import NewswitchConfig
from newswitch.managers.virtual import (
    FilterBankConfig,
    ObjectiveConfig,
    VirtualFilterBankManager,
    VirtualObjectiveManager,
)
from newswitch.protocols.detector import CameraState
from newswitch.protocols.filter_bank import FilterBankState
from newswitch.protocols.illumination import IlluminationKind
from newswitch.protocols.objective import ObjectiveState
from newswitch.protocols.stage import StageState

from .conftest import DocWriter, get_device


@pytest.fixture(autouse=True)
def _locks() -> Iterator[None]:
    """Hold the state locks, as a registered function would, so states can be changed."""
    with acquired_locks("camera_parameters", "stage_position", "filter_bank", "objective"):
        yield


@pytest.fixture
def config(write_doc: DocWriter, minimal_doc: dict[str, Any]) -> NewswitchConfig:
    """The minimal document plus a filter wheel whose first position is empty, loaded.

    Args:
        write_doc: Document writer fixture.
        minimal_doc: The minimal document fixture.

    Returns:
        The loaded configuration.
    """
    devices = minimal_doc["devices"]
    cam = devices["cam"]
    cam["exposure_time_ms"]["preset_vals"] = [1.0, 10.0]
    cam["gain_db"] = {"value": 3.0, "max": 20.0}
    devices["ax-x"]["pos"] = {"min": 0, "max": 50, "unit": "mm"}
    devices["wheel"] = {"type": "stage", "name": "Wheel", "axes": {"rz": "wheel-axis"}}
    devices["wheel-axis"] = {
        "type": "axis",
        "steps_per_um": 1.0,
        "pos": {"preset_vals": {0: "null", 500: "gfp"}},
    }
    devices["mainboard"]["mapping"]["wheel-axis"] = {"type": "canopen-revolver", "id": 5}
    return load_config(write_doc(minimal_doc)).config


def test_illuminations(config: NewswitchConfig) -> None:
    """Slots follow file order; only the first source starts switched on."""
    illuminations = adapters.illuminations(config)
    assert illuminations is not None
    led, laser = illuminations
    assert (led.slot, led.wavelength, led.kind) == (1, 470, IlluminationKind.LED)
    assert (laser.slot, laser.kind) == (2, IlluminationKind.LASER)
    assert led.is_active and led.intensity == led.max_intensity == adapters.FULL_INTENSITY
    assert not laser.is_active and laser.intensity == laser.min_intensity == 0.0


def test_unknown_wavelength(write_doc: DocWriter, minimal_doc: dict[str, Any]) -> None:
    """A light source without wavelength reaches the manager as 0 (broadband/unknown)."""
    del minimal_doc["devices"]["led"]["wavelength"]
    illuminations = adapters.illuminations(load_config(write_doc(minimal_doc)).config)
    assert illuminations is not None and illuminations[0].wavelength == 0.0


def test_detectors(config: NewswitchConfig) -> None:
    """Pixel data are copied and exposure times converted from ms to s."""
    detectors = adapters.detectors(config)
    assert detectors is not None
    (cam,) = detectors
    assert (cam.slot, cam.name, cam.width, cam.height, cam.pixel_size_um) == (
        1,
        "Cam",
        640,
        480,
        5.0,
    )
    assert cam.current_exposure_time == pytest.approx(0.01)
    assert cam.min_exposure_time == pytest.approx(0.0001)
    assert cam.max_exposure_time == pytest.approx(1.0)
    assert cam.preset_exposure_times == pytest.approx([0.001, 0.01])
    assert cam.current_gain == 3.0 and cam.max_gain == 20.0
    assert cam.min_gain == 0.0  # -inf in the file -> Detector default
    assert (cam.key, cam.sensor_width, cam.sensor_height, cam.pixel_pitch_um) == (
        "cam",
        640,
        480,
        5.0,
    )
    assert (cam.current_frame_rate, cam.min_frame_rate, cam.max_frame_rate) == (None, None, None)
    assert cam.current_binning == 1
    assert cam.connection_type is None  # not a camera until `cameras` says so


def test_detectors_frame_rate_and_pixel_size(
    write_doc: DocWriter, minimal_doc: dict[str, Any]
) -> None:
    """Frame rate with its limits, binning and the photosensitive pixel size are copied."""
    cam = minimal_doc["devices"]["cam"]
    cam["framerate_per_sec"] = {"value": 30.0, "min": 1.0}
    cam["binning"] = 2
    cam["pixelsize_um"] = 4.0
    detectors = adapters.detectors(load_config(write_doc(minimal_doc)).config)
    assert detectors is not None
    (detector,) = detectors
    assert (detector.current_frame_rate, detector.min_frame_rate) == (30.0, 1.0)
    assert detector.max_frame_rate is None  # unset limit
    assert detector.current_binning == 2
    assert (detector.pixel_size_um, detector.pixel_pitch_um) == (4.0, 5.0)


def test_detectors_named_presets(write_doc: DocWriter, minimal_doc: dict[str, Any]) -> None:
    """Named presets reach the detector as values in file order, converted to seconds."""
    exposure = minimal_doc["devices"]["cam"]["exposure_time_ms"]
    exposure["preset_vals"] = {100.0: "long", 1.0: "short"}
    exposure["selected_index"] = 0
    detectors = adapters.detectors(load_config(write_doc(minimal_doc)).config)
    assert detectors is not None
    assert detectors[0].preset_exposure_times == pytest.approx([0.1, 0.001])


def test_wheels(config: NewswitchConfig) -> None:
    """An axis whose presets name objectives or filters is a wheel; other names are empty."""
    turret = adapters.wheel_holding(config, ObjectiveDevice)
    assert turret is not None
    assert (turret.key, turret.positions, turret.values) == (
        "turret-axis",
        ["obj10", None, "obj40"],
        [0.0, 1000.0, 2000.0],
    )
    assert turret.selected == 2
    wheel = adapters.wheel_holding(config, FilterConfig)
    assert wheel is not None and wheel.positions == [None, "gfp"] and wheel.selected == 0


def test_objectives_follow_turret(config: NewswitchConfig) -> None:
    """Lenses get file-order slots; the turret's selection sets the default slot."""
    result = adapters.objective_lenses(config)
    assert result is not None
    lenses, default_slot = result
    assert [(lens.slot, lens.name, lens.numerical_aperture) for lens in lenses] == [
        (1, "10x", 0.3),
        (2, "40x", 1.0),
    ]
    assert default_slot == 2  # turret-axis selected_index 2 -> obj40
    state = ObjectiveState()
    VirtualObjectiveManager(state, ObjectiveConfig(objectives=lenses, default_slot=default_slot))
    assert (state.slot, state.name, state.magnification) == (2, "40x", 40.0)


def test_filters_with_empty_position(config: NewswitchConfig) -> None:
    """An empty wheel position becomes the 'Open' filter and is selectable."""
    result = adapters.filters(config)
    assert result is not None
    filters, default_slot = result
    assert [(f.slot, f.name) for f in filters] == [(adapters.OPEN_FILTER_SLOT, "Open"), (1, "GFP")]
    assert default_slot == adapters.OPEN_FILTER_SLOT  # no selection -> first position
    state = FilterBankState()
    VirtualFilterBankManager(state, FilterBankConfig(filters=filters, default_slot=default_slot))
    assert state.get_active_filter().name == "Open"


def test_missing_kinds_return_none(write_doc: DocWriter, minimal_doc: dict[str, Any]) -> None:
    """Without devices of a kind the builders return None (keep manager defaults)."""
    devices = minimal_doc["devices"]
    for key in ("led", "laser", "cam", "obj10", "obj40", "turret", "turret-axis", "gfp"):
        del devices[key]
    devices["mainboard"]["mapping"] = {
        key: entry for key, entry in devices["mainboard"]["mapping"].items() if key in devices
    }
    config = load_config(write_doc(minimal_doc)).config
    assert adapters.illuminations(config) is None
    assert adapters.detectors(config) is None
    assert adapters.objective_lenses(config) is None
    assert adapters.filters(config) is None


def test_motion_stage_skips_wheels(config: NewswitchConfig) -> None:
    """The first stage without a wheel axis moves the sample."""
    found = adapters.motion_stage(config)
    assert found is not None and found[0] == "stage"


def test_stage_limits(config: NewswitchConfig) -> None:
    """Finite travel limits (converted to um) go into the stage state."""
    state = StageState()
    adapters.apply_stage_limits(config, state)
    assert (state.min_x, state.max_x) == (0.0, 50_000.0)
    assert (state.min_z, state.max_z) == (StageState().min_z, StageState().max_z)


def test_serial_settings(write_doc: DocWriter, minimal_doc: dict[str, Any]) -> None:
    """A uc2-rest serial controller yields port and baud rate; a simulated one does not."""
    assert adapters.serial_settings(load_config(write_doc(minimal_doc)).config) is None
    minimal_doc["devices"]["mainboard"]["connection"] = {
        "protocol": "uc2-rest",
        "transport": {"type": "serial", "port": "/dev/ttyUSB0"},
    }
    settings = adapters.serial_settings(load_config(write_doc(minimal_doc)).config)
    assert settings == adapters.SerialSettings(port="/dev/ttyUSB0", baudrate=115200)


def test_sync_runtime_state_and_save(config_path: Path, config: NewswitchConfig) -> None:
    """Runtime values land in the config and survive a save/load cycle."""
    cfg_file = load_config(config_path)  # the file the `config` fixture wrote
    camera_state = CameraState()
    detectors = adapters.detectors(cfg_file.config)
    assert detectors is not None
    camera_state.detectors = detectors
    camera_state.detectors[0].current_exposure_time = 0.5
    stage_state = StageState()
    stage_state.x = 1234.0
    objective_state = ObjectiveState(slot=1)
    filter_bank_state = FilterBankState(current_slot=1)

    adapters.sync_runtime_state(
        cfg_file.config, camera_state, objective_state, filter_bank_state, stage_state
    )
    cfg_file.save(backup=False)

    reloaded = load_config(config_path).config
    exposure = get_device(reloaded, "cam", DetectorConfig).exposure_time_ms
    assert exposure is not None and exposure.value == pytest.approx(500.0)
    turret = get_device(reloaded, "turret-axis", AxisConfig).pos
    assert turret is not None and (turret.selected_index, turret.value) == (0, 0.0)
    wheel = get_device(reloaded, "wheel-axis", AxisConfig).pos
    assert wheel is not None and (wheel.selected_index, wheel.value) == (1, 500.0)
    x_pos = get_device(reloaded, "ax-x", AxisConfig).pos
    assert x_pos is not None and x_pos.value == pytest.approx(1234.0)


def test_sync_skips_out_of_range_values(config: NewswitchConfig) -> None:
    """A runtime value outside the configured limits is not stored."""
    camera_state = CameraState()
    detectors = adapters.detectors(config)
    assert detectors is not None
    camera_state.detectors = detectors
    camera_state.detectors[0].current_exposure_time = 50.0  # 50 000 ms > max 1000 ms
    adapters.sync_runtime_state(
        config, camera_state, ObjectiveState(), FilterBankState(), StageState()
    )
    exposure = get_device(config, "cam", DetectorConfig).exposure_time_ms
    assert exposure is not None and exposure.value == 10.0


# ---------------------------------------------------------------------------
# Cameras
# ---------------------------------------------------------------------------


def _camera_doc(
    doc: dict[str, Any],
    connection: dict[str, Any],
    entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Move the detector "cam" from the mainboard to a camera controller.

    Args:
        doc: The minimal document; modified in place.
        connection: Connection of the camera controller.
        entry: Further keys of the camera's mapping entry.

    Returns:
        `doc`.
    """
    devices = doc["devices"]
    del devices["mainboard"]["mapping"]["cam"]
    devices["cam-sdk"] = {
        "type": "controller",
        "connection": connection,
        "mapping": {"cam": {"type": "camera", "id": 0, **(entry or {})}},
    }
    devices["cam"]["manufacturer"] = "SomeVendor"
    return doc


def test_cameras(write_doc: DocWriter, minimal_doc: dict[str, Any]) -> None:
    """A detector behind a GigE Vision controller becomes a camera; values pass unchanged."""
    entry = {
        "serial_number": "SN-42",
        "buffer_size": 8,
        "vendor_options": {"sensor_width": 320, "mode": "fast"},
    }
    doc = _camera_doc(minimal_doc, {"protocol": "gige-vision"}, entry)
    doc["devices"]["cam"]["gain_db"] = {"value": 2.5}
    doc["devices"]["cam"]["framerate_per_sec"] = {"value": 30.0}
    doc["devices"]["cam"]["binning"] = 2
    found = adapters.cameras(load_config(write_doc(doc)).config)
    assert found is not None
    (camera,), vendor_options = found
    assert (camera.slot, camera.key, camera.name) == (1, "cam", "Cam")
    assert (camera.manufacturer, camera.connection_type) == ("SomeVendor", "GigE")
    assert (camera.serial_number, camera.device_index) == ("SN-42", None)
    assert (camera.buffer_size, camera.store_image_data) == (8, None)  # set when opened
    assert vendor_options == {1: {"sensor_width": 320, "mode": "fast"}}
    assert camera.current_exposure_time == pytest.approx(0.01)
    assert (camera.current_gain, camera.current_frame_rate) == (2.5, 30.0)
    assert camera.current_binning == 2
    assert (camera.sensor_width, camera.sensor_height) == (640, 480)  # all of `detectors`


def test_cameras_defaults(write_doc: DocWriter, minimal_doc: dict[str, Any]) -> None:
    """Unset camera keys stay None, so the camera library's defaults apply."""
    doc = _camera_doc(minimal_doc, {"protocol": "usb3-vision"})
    del doc["devices"]["cam"]["manufacturer"]
    found = adapters.cameras(load_config(write_doc(doc)).config)
    assert found is not None
    (camera,), vendor_options = found
    assert camera.connection_type == "USB3"
    assert camera.manufacturer is None
    assert (camera.serial_number, camera.device_index) == (None, None)
    assert (camera.buffer_size, camera.store_image_data) == (None, None)
    assert vendor_options == {1: {}}
    assert camera.current_frame_rate is None  # not configured: the camera keeps its own


@pytest.mark.parametrize(
    ("entry", "selector"),
    [
        (None, (None, 2)),  # the connection's selector
        ({"serial_number": "SN-1"}, ("SN-1", None)),  # the mapping entry's wins
        ({"index": 0}, (None, 0)),
    ],
)
def test_camera_selector(
    write_doc: DocWriter,
    minimal_doc: dict[str, Any],
    entry: dict[str, Any] | None,
    selector: tuple[str | None, int | None],
) -> None:
    """serial_number/index come from the mapping entry, else from the connection."""
    doc = _camera_doc(minimal_doc, {"protocol": "usb3-vision", "index": 2}, entry)
    found = adapters.cameras(load_config(write_doc(doc)).config)
    assert found is not None
    (camera,), _ = found
    assert (camera.serial_number, camera.device_index) == selector


def test_cameras_skip_other_detectors(
    write_doc: DocWriter, minimal_doc: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    """Detectors without a camera controller are skipped; slots count all detectors."""
    doc = _camera_doc(minimal_doc, {"protocol": "gige-vision"})
    devices = doc["devices"]
    doc["devices"] = {"diode": {"type": "detector", "name": "Diode"}, **devices}
    found = adapters.cameras(load_config(write_doc(doc)).config)
    assert found is not None
    cameras, vendor_options = found
    assert [(camera.key, camera.slot) for camera in cameras] == [("cam", 2)]
    assert list(vendor_options) == [2]
    assert "'diode' is not mapped to a camera controller" in caplog.text


@pytest.mark.parametrize("value", [True, False, "yes"])
def test_store_image_data_is_ignored(
    write_doc: DocWriter,
    minimal_doc: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
    value: object,
) -> None:
    """The former key store_image_data is ignored with a warning, whatever its value."""
    doc = _camera_doc(minimal_doc, {"protocol": "usb3-vision"}, {"store_image_data": value})
    found = adapters.cameras(load_config(write_doc(doc)).config)
    assert found is not None
    (camera,), _ = found
    assert camera.store_image_data is None
    assert "devices.cam-sdk.mapping.cam.store_image_data is ignored" in caplog.text


def test_no_cameras(write_doc: DocWriter, minimal_doc: dict[str, Any]) -> None:
    """A detector behind a non-camera controller (here: simulated) is no camera."""
    assert adapters.cameras(load_config(write_doc(minimal_doc)).config) is None


@pytest.mark.parametrize(
    ("connection", "entry", "problem"),
    [
        ({}, {"serial_number": 1234}, "serial_number: must be a non-empty string"),
        ({}, {"serial_number": ""}, "serial_number: must be a non-empty string"),
        ({}, {"index": -1}, "index: must be an integer >= 0"),
        ({}, {"index": True}, "index: must be an integer >= 0"),
        ({}, {"buffer_size": 1}, "buffer_size: must be an integer >= 2"),
        ({}, {"vendor_options": [1, 2]}, "vendor_options: must be a mapping"),
        ({}, {"serial_number": "SN-1", "index": 0}, "serial_number and index both"),
        ({"serial_number": "SN-1", "index": 0}, {}, "serial_number and index both"),
    ],
)
def test_invalid_camera_keys(
    write_doc: DocWriter,
    minimal_doc: dict[str, Any],
    connection: dict[str, Any],
    entry: dict[str, Any],
    problem: str,
) -> None:
    """Invalid camera keys are reported with the path of the mapping entry."""
    doc = _camera_doc(minimal_doc, {"protocol": "usb3-vision", **connection}, entry)
    config = load_config(write_doc(doc)).config
    with pytest.raises(ConfigError) as error:
        adapters.cameras(config)
    (reported,) = error.value.problems
    assert reported.startswith("devices.cam-sdk.mapping.cam")
    assert problem in reported
