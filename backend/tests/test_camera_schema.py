"""Tests for `CameraSchema`: required fields, derived geometry and cross-field rules.

These are the rules that live in Pydantic only — the exported JSON Schema checks
structure and types, but cannot fill in a default from a sibling field or compare an
ROI against the sensor size.
"""

from typing import Any

import pytest
from pydantic import ValidationError

from newswitch.schemas import CameraSchema


@pytest.mark.parametrize("missing", ["name", "pixelcount", "pixelpitch_um"])
def test_required_fields(camera_doc: dict[str, Any], missing: str) -> None:
    """`name`, `pixelcount` and `pixelpitch_um` have no default and are required.

    Args:
        camera_doc: The valid camera document fixture.
        missing: Key removed before validation.
    """
    camera_doc.pop(missing)
    with pytest.raises(ValidationError, match=missing):
        CameraSchema.model_validate(camera_doc)


def test_optional_fields_may_be_omitted() -> None:
    """Everything else is optional: a model description needs no serial or exposure."""
    camera = CameraSchema.model_validate(
        {"name": "Minimal", "pixelcount": {"x": 640, "y": 480}, "pixelpitch_um": {"x": 5.0}}
    )
    assert camera.camera_id is None
    assert camera.exposure_time_ms is None
    assert camera.channels == 1
    assert camera.binning == 1
    assert camera.tags == []
    assert camera.type == "camera"


def test_pixelpitch_y_defaults_to_x(camera_doc: dict[str, Any]) -> None:
    """Square pixels are the common case, so `y` may be omitted.

    Args:
        camera_doc: The valid camera document fixture.
    """
    camera = CameraSchema.model_validate(camera_doc)
    assert camera.pixelpitch_um.x == 10.0
    assert camera.pixelpitch_um.y == 10.0


def test_pixelsize_defaults_to_pixelpitch(camera_doc: dict[str, Any]) -> None:
    """An omitted `pixelsize_um` means a fill factor of 1.0.

    Args:
        camera_doc: The valid camera document fixture.
    """
    camera = CameraSchema.model_validate(camera_doc)
    assert camera.pixelsize_um is not None
    assert (camera.pixelsize_um.x, camera.pixelsize_um.y) == (10.0, 10.0)
    assert camera.fill_factor == pytest.approx(1.0)


def test_pixelsize_y_falls_back_to_pixelsize_x(camera_doc: dict[str, Any]) -> None:
    """`pixelsize_um.y` falls back to `pixelsize_um.x`, *not* to `pixelpitch_um.y`.

    Both are `Vector2Float`, so each object fills its own `y` from its own `x`.
    Worth pinning: for a non-square pitch this is the surprising half of the rule.

    Args:
        camera_doc: The valid camera document fixture.
    """
    camera_doc["pixelpitch_um"] = {"x": 10.0, "y": 20.0}
    camera_doc["pixelsize_um"] = {"x": 8.0}
    camera = CameraSchema.model_validate(camera_doc)
    assert camera.pixelsize_um is not None
    assert camera.pixelsize_um.y == 8.0
    assert camera.fill_factor == pytest.approx((8.0 * 8.0) / (10.0 * 20.0))


def test_sensor_size_mm(camera_doc: dict[str, Any]) -> None:
    """Sensor extent is pixelcount times pitch, converted to millimeters.

    Args:
        camera_doc: The valid camera document fixture.
    """
    camera = CameraSchema.model_validate(camera_doc)
    assert camera.sensor_size_mm == pytest.approx((19.2, 12.0))


def test_roi_within_sensor_accepted(camera_doc: dict[str, Any]) -> None:
    """An ROI that fits inside the sensor is fine.

    Args:
        camera_doc: The valid camera document fixture.
    """
    camera_doc["roi"] = (0, 0, 1920, 1200)
    assert CameraSchema.model_validate(camera_doc).roi == (0, 0, 1920, 1200)


@pytest.mark.parametrize(
    ("roi", "message"),
    [
        ((0, 0, 1921, 1200), "exceeds sensor pixelcount"),
        ((100, 100, 1900, 100), "exceeds sensor pixelcount"),
        ((-1, 0, 100, 100), "must be non-negative"),
        ((0, 0, 0, 100), "must be positive"),
    ],
)
def test_roi_cross_field_rules(
    camera_doc: dict[str, Any], roi: tuple[int, int, int, int], message: str
) -> None:
    """The ROI is checked against `pixelcount` — a rule JSON Schema cannot express.

    Args:
        camera_doc: The valid camera document fixture.
        roi: The region of interest under test.
        message: Fragment expected in the error message.
    """
    camera_doc["roi"] = roi
    with pytest.raises(ValidationError, match=message):
        CameraSchema.model_validate(camera_doc)


def test_software_trigger_rejects_edge(camera_doc: dict[str, Any]) -> None:
    """`edge`/`level` are meaningless for a software trigger and treated as a mistake.

    Args:
        camera_doc: The valid camera document fixture.
    """
    camera_doc["trigger"] = {"type": "software", "edge": "rising"}
    with pytest.raises(ValidationError, match="only meaningful for hardware"):
        CameraSchema.model_validate(camera_doc)


def test_hardware_trigger_accepts_edge(camera_doc: dict[str, Any]) -> None:
    """A hardware trigger may name the edge it fires on.

    Args:
        camera_doc: The valid camera document fixture.
    """
    camera = CameraSchema.model_validate(camera_doc)
    assert camera.trigger is not None
    assert (camera.trigger.type, camera.trigger.edge) == ("hardware", "rising")


def test_unknown_key_rejected(camera_doc: dict[str, Any]) -> None:
    """`extra="forbid"` turns a typo into an error instead of a silently lost setting.

    Args:
        camera_doc: The valid camera document fixture.
    """
    camera_doc["pixelcont"] = {"x": 1, "y": 1}
    with pytest.raises(ValidationError, match="pixelcont"):
        CameraSchema.model_validate(camera_doc)


@pytest.mark.parametrize("binning", [0, 3, 8])
def test_binning_is_a_closed_set(camera_doc: dict[str, Any], binning: int) -> None:
    """Only symmetric binning factors 1, 2 and 4 exist on the supported hardware.

    Args:
        camera_doc: The valid camera document fixture.
        binning: The rejected binning factor.
    """
    camera_doc["binning"] = binning
    with pytest.raises(ValidationError):
        CameraSchema.model_validate(camera_doc)


def test_type_discriminator_is_fixed(camera_doc: dict[str, Any]) -> None:
    """A camera document cannot claim to be another device type.

    Args:
        camera_doc: The valid camera document fixture.
    """
    camera_doc["type"] = "stage"
    with pytest.raises(ValidationError):
        CameraSchema.model_validate(camera_doc)


def test_schema_pointer_round_trips(camera_doc: dict[str, Any]) -> None:
    """The `$schema` editor pointer is read into `schema_ref` and written back as-is.

    Args:
        camera_doc: The valid camera document fixture.
    """
    camera_doc["$schema"] = "./schemas/camera.schema.json"
    camera = CameraSchema.model_validate(camera_doc)
    assert camera.schema_ref == "./schemas/camera.schema.json"

    dumped = camera.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert dumped["$schema"] == "./schemas/camera.schema.json"
    assert "schema_ref" not in dumped


def test_pixelcount_must_be_positive_integers(camera_doc: dict[str, Any]) -> None:
    """A sensor with no pixels is not a sensor.

    Args:
        camera_doc: The valid camera document fixture.
    """
    camera_doc["pixelcount"] = {"x": 0, "y": 1200}
    with pytest.raises(ValidationError):
        CameraSchema.model_validate(camera_doc)
