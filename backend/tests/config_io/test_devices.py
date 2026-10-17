"""Tests for the device dataclasses: defaults, required keys and per-device rules."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from newswitch.config_io import (
    DEVICE_TYPES,
    AxisConfig,
    ControllerConfig,
    DetectorConfig,
    Device,
    FilterConfig,
    LightsourceConfig,
    NewswitchConfig,
    StageConfig,
    field_markers,
)

from .conftest import SIMULATED

DEVICE = TypeAdapter(Device)


def _device(data: dict[str, Any]) -> Any:  # noqa: ANN401 - any device class
    return DEVICE.validate_python(data)


def _controller(mapping: dict[str, Any]) -> Any:  # noqa: ANN401 - any device class
    return _device({"type": "controller", "connection": SIMULATED, "mapping": mapping})


def test_every_type_is_a_dataclass() -> None:
    """The interface towards newswitch consists of real dataclasses."""
    assert set(DEVICE_TYPES) == {
        "lightsource",
        "detector",
        "controller",
        "stage",
        "axis",
        "objective",
        "filter",
    }
    for cls in DEVICE_TYPES.values():
        assert dataclasses.is_dataclass(cls)


def test_common_defaults() -> None:
    """name, manufacturer and tags are optional for every type."""
    light = _device({"type": "lightsource"})
    assert light.name is None and light.manufacturer is None and light.tags == []


def test_name_defaults_to_key(minimal_doc: dict[str, Any]) -> None:
    """A device without name is named after its key."""
    config = TypeAdapter(NewswitchConfig).validate_python(minimal_doc)
    assert config.devices["ax-x"].name == "ax-x"
    assert config.devices["cam"].name == "Cam"


def test_lightsource_defaults() -> None:
    """Unstated light source keys take the table's defaults."""
    light = _device({"type": "lightsource"})
    assert isinstance(light, LightsourceConfig)
    assert light.wavelength is None and light.bandwidth is None and light.spec_shape is None
    assert light.channels == 1
    assert light.coherence == "incoherent"
    assert light.polarization == "random"
    assert light.pulse_length is None and light.pulse_length_unit is None
    assert light.trigger is None


def test_detector_defaults_and_pairs() -> None:
    """Detector pairs resolve square geometry; pixelsize falls back to the pitch."""
    cam = _device({"type": "detector", "pixelcount": [100, 50], "pixelpitch_um": 4.0})
    assert isinstance(cam, DetectorConfig)
    assert cam.binning == 1 and cam.channels == 1 and cam.exposure_time_ms is None
    assert cam.pixelpitch_xy == (4.0, 4.0)
    assert cam.pixelsize_xy == (4.0, 4.0)
    assert cam.sensor_size_mm == pytest.approx((0.4, 0.2))


@pytest.mark.parametrize(
    "extra",
    [
        {"pixelpitch_um": 4.0, "pixelsize_um": 4.5},
        {"pixelpitch_um": [4.0, 3.0], "pixelsize_um": [3.0, 3.5]},
        {"binning": 3},
        {"pixelcount": [0, 10]},
        {"exposure_time_ms": 0},
        {"gain_db": -1},
        {"framerate_per_sec": {"value": -2}},
    ],
)
def test_detector_invalid(extra: dict[str, Any]) -> None:
    """Pixel size above pitch, bad binning and negative values are rejected."""
    with pytest.raises(ValidationError):
        _device({"type": "detector", **extra})


def test_axis_defaults_and_units() -> None:
    """steps_per_um is required but may be null; values in mm are converted into um."""
    axis = _device(
        {"type": "axis", "steps_per_um": None, "pos": {"min": 0, "max": 100, "unit": "mm"}}
    )
    assert isinstance(axis, AxisConfig)
    assert axis.steps_per_um is None  # servo
    assert axis.inverted is False and axis.homing_required is False
    assert axis.pos is not None and axis.pos.max == pytest.approx(100_000.0)
    assert axis.pos.unit == "um"
    assert axis.vel is None and axis.acc is None and axis.jerk is None


@pytest.mark.parametrize(
    "data",
    [
        {},  # steps_per_um missing
        {"steps_per_um": 0},
        {"steps_per_um": 1.0, "vel": 0},
        {"steps_per_um": 1.0, "acc": {"value": -1}},
    ],
)
def test_axis_invalid(data: dict[str, Any]) -> None:
    """An axis needs steps_per_um; velocity, acceleration and jerk are positive."""
    with pytest.raises(ValidationError):
        _device({"type": "axis", **data})


def test_stage_axes_and_homing_order() -> None:
    """A stage names its axes by direction; homing_order must list each exactly once."""
    stage = _device({"type": "stage", "axes": {"x": "ax-1", "z": "ax-2"}})
    assert isinstance(stage, StageConfig)
    assert stage.homing_order is None  # home all axes in parallel
    _device({"type": "stage", "axes": {"x": "ax-1", "z": "ax-2"}, "homing_order": ["z", "x"]})

    for data in (
        {"axes": {}},
        {"axes": {"x": "ax-1", "z": "ax-2"}, "homing_order": ["z"]},
        {"axes": {"x": "ax-1"}, "homing_order": ["x", "x"]},
        {"axes": {"x": "ax-1"}, "homing_order": ["x", "y"]},
    ):
        with pytest.raises(ValidationError):
            _device({"type": "stage", **data})


def test_controller_needs_connection_and_mapping() -> None:
    """Firmware is optional, connection and mapping are not."""
    controller = _controller({})
    assert isinstance(controller, ControllerConfig)
    assert controller.firmware.name is None and controller.firmware.version is None
    with pytest.raises(ValidationError):
        _device({"type": "controller", "mapping": {}})
    with pytest.raises(ValidationError):
        _device({"type": "controller", "connection": SIMULATED})


def test_mapping_entry_defaults() -> None:
    """subid defaults to 0, pwm_max to None."""
    entry = _controller({"ax": {"type": "canopen-motor", "id": 3}}).mapping["ax"]
    assert (entry.id, entry.subid, entry.pwm_max, entry.address) == (3, 0, None, (3, 0))


@pytest.mark.parametrize(
    ("entry", "match"),
    [
        ({"type": "canopen-laser", "id": 1}, "needs pwm_max"),
        ({"type": "PWM-led", "id": 1}, "needs pwm_max"),
        ({"type": "canopen-motor", "id": 1, "pwm_max": 255}, "only valid for PWM"),
        ({"type": "canopen-motor", "id": -1}, "greater than or equal to 0"),
        ({"type": "canopen-motor"}, "id"),
    ],
)
def test_mapping_entry_invalid(entry: dict[str, Any], match: str) -> None:
    """pwm_max belongs to PWM outputs only (type containing laser or pwm); ids are >= 0."""
    with pytest.raises(ValidationError, match=match):
        _controller({"dev": entry})


def test_address_used_twice() -> None:
    """Two devices on one controller cannot share id and subid."""
    _controller({"a": {"type": "m", "id": 1}, "b": {"type": "m", "id": 1, "subid": 1}})
    with pytest.raises(ValidationError, match="id 1/subid 0 is used by a, b"):
        _controller({"a": {"type": "m", "id": 1}, "b": {"type": "m", "id": 1}})


def test_further_keys_are_kept() -> None:
    """Keys the schema does not know land in extras, for devices and mapping entries."""
    axis = _device({"type": "axis", "steps_per_um": 1.0, "optikit_dsn_variable": "sample-x"})
    assert axis.extras == {"optikit_dsn_variable": "sample-x"}
    entry = _controller({"cam": {"type": "gige", "id": 0, "serial_number": "ab"}}).mapping["cam"]
    assert entry.extras == {"serial_number": "ab"}
    # they survive a dump and a revalidation (as in ConfigFile.apply_firmware)
    assert DEVICE.validate_python(DEVICE.dump_python(axis)).extras == axis.extras


@pytest.mark.parametrize(
    "data",
    [
        {"type": "objective", "magnification": 10, "na": 0.3},  # wd missing
        {"type": "objective", "magnification": 10, "na": 0, "wd": 1},
        {"type": "filter", "wavelength": 500, "transmission": 1.2},
        {"type": "filter", "wavelength": 0},
        {"type": "lightsource", "wavelength": 0},
        {"type": "lightsource", "pulse_length": -1},
        {"type": "lightsource", "polarization": "circ"},
        {"type": "revolver", "channels": []},
        {"type": "laser", "wavelength": 500},
    ],
)
def test_invalid_passive_and_misc(data: dict[str, Any]) -> None:
    """Required keys, ranges and unknown types are enforced."""
    with pytest.raises(ValidationError):
        _device(data)


def test_filter_wavelength_is_optional() -> None:
    """A filter of unknown wavelength is valid."""
    flt = _device({"type": "filter"})
    assert isinstance(flt, FilterConfig) and flt.wavelength is None and flt.transmission == 1.0


def test_slots_and_lookups(minimal_doc: dict[str, Any]) -> None:
    """Slots count 1, 2, ... per device type in file order; stage axes and controllers resolve."""
    config = TypeAdapter(NewswitchConfig).validate_python(minimal_doc)
    assert [config.slot_of(key) for key in ("led", "laser")] == [1, 2]
    assert config.slot_of("obj40") == 2
    assert config.slot_of("turret-axis") == 3
    assert list(config.keyed(StageConfig)) == ["stage", "turret"]
    assert [axis.name for axis in config.stage_axes(config.stages[0]).values()] == ["ax-x", "ax-z"]
    controller = config.controller_of("ax-z")
    assert controller is not None and controller[0] == "mainboard" and controller[1].id == 13
    assert config.controller_of("gfp") is None


def test_firmware_markers() -> None:
    """Firmware-provided fields are marked; physical values carry their unit."""
    markers = field_markers(DetectorConfig)
    assert markers["exposure_time_ms"] == {"x_unit": "ms", "x_firmware": "limits"}
    assert markers["pixelcount"] == {"x_firmware": "full"}
    assert markers["manufacturer"] == {"x_firmware": "full"}
    assert "trigger" not in markers and "name" not in markers
    axis = field_markers(AxisConfig)
    assert axis["pos"] == {"x_unit": "um", "x_firmware": "full"}
    assert axis["steps_per_um"] == axis["homing_required"] == {"x_firmware": "full"}
    assert "inverted" not in axis
    assert "channels" in field_markers(LightsourceConfig)
