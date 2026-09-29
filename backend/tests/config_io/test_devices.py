"""Tests for the device dataclasses: defaults, required keys and per-device rules."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from newswitch.config_io import (
    DEVICE_TYPES,
    DetectorConfig,
    Device,
    LightsourceConfig,
    NewswitchConfig,
    RevolverConfig,
    StageConfig,
    field_markers,
)

DEVICE = TypeAdapter(Device)
CONTROLLED = {"controller": "mainboard"}


def _device(data: dict[str, Any]) -> Any:  # noqa: ANN401 - any device class
    return DEVICE.validate_python({"name": "n", "device_id": "d", **data})


def test_every_type_is_a_dataclass() -> None:
    """The interface towards newswitch consists of real dataclasses."""
    for cls in DEVICE_TYPES.values():
        assert dataclasses.is_dataclass(cls)


def test_lightsource_defaults() -> None:
    """Unstated light source keys take the table's defaults."""
    light = _device({"type": "lightsource", "wavelength": 488, **CONTROLLED})
    assert isinstance(light, LightsourceConfig)
    assert light.channels == 1
    assert light.coherence == "incoherent"
    assert light.polarization == "random"
    assert light.max_intensity is None and light.bandwidth is None and light.trigger is None
    assert light.manufacturer is None and light.tags == []


def test_detector_defaults_and_pairs() -> None:
    """Detector pairs resolve square geometry; pixelsize falls back to the pitch."""
    cam = _device({"type": "detector", "pixelcount": [100, 50], "pixelpitch_um": 4.0, **CONTROLLED})
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
        _device({"type": "detector", **CONTROLLED, **extra})


def test_connection_or_controller() -> None:
    """Connected devices need exactly one of connection and controller."""
    with pytest.raises(ValidationError, match="either"):
        _device({"type": "lightsource", "wavelength": 488})
    with pytest.raises(ValidationError, match="mutually exclusive"):
        _device(
            {
                "type": "lightsource",
                "wavelength": 488,
                "controller": "mainboard",
                "connection": {"protocol": "gige-vision"},
            }
        )


def test_controller_requires_connection_and_firmware() -> None:
    """A controller without connection or firmware is invalid."""
    with pytest.raises(ValidationError):
        _device({"type": "controller", "firmware": {"name": "f", "version": "1"}})
    with pytest.raises(ValidationError):
        _device({"type": "controller", "connection": {"protocol": "gige-vision"}})


def test_stage_axes() -> None:
    """steps_per_um is required but may be null; labels are unique and restricted."""
    stage = _device(
        {
            "type": "stage",
            **CONTROLLED,
            "axes": [
                {"label": "x", "steps_per_um": None, "homing_required": True},
                {"label": "rz", "steps_per_um": 2.0, "homing_required": False},
            ],
        }
    )
    assert isinstance(stage, StageConfig)
    assert stage.axis("x") is not None and stage.axis("x").inverted is False
    assert stage.axis("y") is None

    for axes in (
        [{"label": "x", "homing_required": True}],  # steps_per_um missing
        [{"label": "x", "steps_per_um": 1.0}],  # homing_required missing
        [{"label": "b", "steps_per_um": 1.0, "homing_required": True}],
        [{"label": "x", "steps_per_um": 1.0, "homing_required": True}] * 2,
        [],
        [{"label": "x", "steps_per_um": 1.0, "homing_required": True, "travel_um": 5}],
    ):
        with pytest.raises(ValidationError):
            _device({"type": "stage", **CONTROLLED, "axes": axes})


def test_axis_units_are_converted() -> None:
    """Axis values in mm are converted into um."""
    stage = _device(
        {
            "type": "stage",
            **CONTROLLED,
            "axes": [
                {
                    "label": "x",
                    "steps_per_um": 1.0,
                    "homing_required": True,
                    "pos": {"min": 0, "max": 100, "unit": "mm"},
                },
            ],
        }
    )
    assert stage.axes[0].pos.max == pytest.approx(100_000.0)
    assert stage.axes[0].pos.unit == "um"


def test_revolver() -> None:
    """selected_channel must point into channels."""
    revolver = _device(
        {"type": "revolver", **CONTROLLED, "channels": ["a", None, "b"], "selected_channel": 1}
    )
    assert isinstance(revolver, RevolverConfig)
    assert revolver.selected_device_id is None
    with pytest.raises(ValidationError):
        _device({"type": "revolver", **CONTROLLED, "channels": ["a"], "selected_channel": 1})
    with pytest.raises(ValidationError):
        _device({"type": "revolver", **CONTROLLED, "channels": []})


@pytest.mark.parametrize(
    "data",
    [
        {"type": "objective", "magnification": 10, "na": 0.3},  # wd missing
        {"type": "objective", "magnification": 10, "na": 0, "wd": 1},
        {"type": "filter", "wavelength": 500, "transmission": 1.2},
        {"type": "filter"},
        {"type": "lightsource", "wavelength": 500, "polarization": "circ", **CONTROLLED},
        {"type": "laser", "wavelength": 500},
    ],
)
def test_invalid_passive_and_misc(data: dict[str, Any]) -> None:
    """Required keys, ranges and unknown types are enforced."""
    with pytest.raises(ValidationError):
        _device(data)


def test_slot_follows_file_order(minimal_doc: dict[str, Any]) -> None:
    """Slots count 1, 2, ... per device type in file order."""
    for key, entry in minimal_doc["devices"].items():
        entry["device_id"] = key
    config = TypeAdapter(NewswitchConfig).validate_python(minimal_doc)
    assert [config.slot_of(d.device_id) for d in config.lightsources] == [1, 2]
    assert config.slot_of("obj40") == 2
    assert config.slot_of("gfp") == 1
    assert [d.device_id for d in config.objectives] == ["obj10", "obj40"]


def test_firmware_markers() -> None:
    """Firmware-provided fields are marked; physical values carry their unit."""
    markers = field_markers(DetectorConfig)
    assert markers["exposure_time_ms"] == {"x_unit": "ms", "x_firmware": "limits"}
    assert markers["pixelcount"] == {"x_firmware": "full"}
    assert "trigger" not in markers and "name" not in markers
