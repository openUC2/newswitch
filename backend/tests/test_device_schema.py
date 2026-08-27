"""Tests for the device models and the `DeviceRegistry` that holds them.

Focus: the discriminated union dispatches each entry to exactly one model, and the
uniqueness rules (device identifiers, axis labels, filter slots) that keep a setup
description unambiguous.
"""

from typing import Any

import pytest
from pydantic import ValidationError

from newswitch.schemas import (
    CameraDevice,
    DeviceRegistry,
    FilterWheelDevice,
    LaserDevice,
    StageDevice,
)


def test_registry_dispatches_by_type(registry_doc: dict[str, Any]) -> None:
    """Each entry becomes the model its `type` names, not a generic base object.

    Args:
        registry_doc: The valid multi-device document fixture.
    """
    registry = DeviceRegistry.model_validate(registry_doc)
    assert [type(dev) for dev in registry.devices] == [
        CameraDevice,
        StageDevice,
        LaserDevice,
        FilterWheelDevice,
    ]
    assert registry.setup == "test-bench"
    assert registry.version == 1


def test_empty_registry_is_valid() -> None:
    """A setup with no devices yet is a legitimate starting point."""
    assert DeviceRegistry().devices == []


def test_discriminator_error_names_the_type(registry_doc: dict[str, Any]) -> None:
    """An unknown `type` is reported as such instead of as a union failure.

    Args:
        registry_doc: The valid multi-device document fixture.
    """
    registry_doc["devices"][0]["type"] = "spectrometer"
    with pytest.raises(ValidationError, match="spectrometer"):
        DeviceRegistry.model_validate(registry_doc)


def test_error_path_points_at_the_field(registry_doc: dict[str, Any]) -> None:
    """The discriminator keeps error locations precise inside the offending entry.

    Args:
        registry_doc: The valid multi-device document fixture.
    """
    registry_doc["devices"][1]["axes"][0]["travel_um"] = -1.0
    with pytest.raises(ValidationError) as excinfo:
        DeviceRegistry.model_validate(registry_doc)

    location = excinfo.value.errors()[0]["loc"]
    assert "travel_um" in location
    assert "stage" in str(location)


def test_by_type(registry_doc: dict[str, Any]) -> None:
    """`by_type` filters the registry without the caller writing a comprehension.

    Args:
        registry_doc: The valid multi-device document fixture.
    """
    registry = DeviceRegistry.model_validate(registry_doc)
    assert [dev.name for dev in registry.by_type("camera")] == ["TestCam-2000"]
    assert registry.by_type("spectrometer") == []


def test_get_by_id_and_by_name(registry_doc: dict[str, Any]) -> None:
    """Lookup accepts the identifier of the unit as well as the model name.

    Args:
        registry_doc: The valid multi-device document fixture.
    """
    registry = DeviceRegistry.model_validate(registry_doc)
    assert registry.get("laser-001").name == "LD-488"
    assert registry.get("LD-488").name == "LD-488"
    assert registry.get("testcam-001").name == "TestCam-2000"

    with pytest.raises(KeyError, match="nope"):
        registry.get("nope")


def test_key_precedence() -> None:
    """`DeviceBase.key` is `device_id` when set and the name otherwise.

    One identifier field for every device type: cameras used to carry their own
    `camera_id`, which the merge into `DeviceBase` removed.
    """
    stage = StageDevice(
        type="stage",
        name="XY",
        device_id="stage-007",
        axes=[{"label": "x", "travel_um": 1.0, "steps_per_um": 1.0}],  # type: ignore[list-item]
    )
    camera = CameraDevice(
        type="camera",
        name="Cam",
        device_id="cam-007",
        pixelcount={"x": 1, "y": 1},  # type: ignore[arg-type]
        pixelpitch_um={"x": 1.0},  # type: ignore[arg-type]
    )
    anonymous = LaserDevice(type="laser", name="LD-405", wavelength_nm=405.0, max_power_mw=10.0)

    assert stage.key == "stage-007"
    assert camera.key == "cam-007"
    assert anonymous.key == "LD-405"


def test_duplicate_identifiers_rejected(registry_doc: dict[str, Any]) -> None:
    """Two devices with the same key would make `get()` ambiguous.

    Args:
        registry_doc: The valid multi-device document fixture.
    """
    registry_doc["devices"][2]["device_id"] = "stage-001"
    with pytest.raises(ValidationError, match="duplicate identifier 'stage-001'"):
        DeviceRegistry.model_validate(registry_doc)


def test_duplicate_names_rejected_when_ids_are_absent(registry_doc: dict[str, Any]) -> None:
    """Without identifiers the name is the key, so it has to be unique too.

    Args:
        registry_doc: The valid multi-device document fixture.
    """
    for device in registry_doc["devices"][1:3]:
        device.pop("device_id")
        device["name"] = "Twin"
    with pytest.raises(ValidationError, match="duplicate identifier 'Twin'"):
        DeviceRegistry.model_validate(registry_doc)


def test_stage_axis_rules(registry_doc: dict[str, Any]) -> None:
    """A stage needs at least one axis and cannot list the same label twice.

    Args:
        registry_doc: The valid multi-device document fixture.
    """
    stage = registry_doc["devices"][1]

    stage["axes"] = []
    with pytest.raises(ValidationError, match="at least 1 item"):
        DeviceRegistry.model_validate(registry_doc)

    stage["axes"] = [
        {"label": "x", "travel_um": 1000.0, "steps_per_um": 1.0},
        {"label": "x", "travel_um": 1000.0, "steps_per_um": 1.0},
    ]
    with pytest.raises(ValidationError, match="duplicate axis labels"):
        DeviceRegistry.model_validate(registry_doc)


def test_filterwheel_slot_rules(registry_doc: dict[str, Any]) -> None:
    """Two filters cannot sit in the same slot of the wheel.

    Args:
        registry_doc: The valid multi-device document fixture.
    """
    registry_doc["devices"][3]["slots"][1]["position"] = 0
    with pytest.raises(ValidationError, match="duplicate slot positions"):
        DeviceRegistry.model_validate(registry_doc)


def test_unknown_root_key_rejected(registry_doc: dict[str, Any]) -> None:
    """`extra="forbid"` applies to the registry itself, not just to the devices.

    Args:
        registry_doc: The valid multi-device document fixture.
    """
    registry_doc["setups"] = "typo"
    with pytest.raises(ValidationError, match="setups"):
        DeviceRegistry.model_validate(registry_doc)
