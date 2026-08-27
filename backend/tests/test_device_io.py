"""Tests for `device_io`: per-type validation, loading, writing and describing.

The module exists to avoid `oneOf` noise: a mixed device list validated against one
JSON Schema reports every branch it tried. `validate_registry` reads the `type` field
first and checks the entry against that sub-schema only, so the messages point at the
actual field. These tests pin that error shape, since it is the user-facing part.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from newswitch.schemas import (
    ConfigError,
    DeviceConfigError,
    describe,
    dump_devices,
    export_devices_schema,
    load_devices,
    validate_registry,
)
from tests.conftest import ConfigWriter


@pytest.fixture
def broken_doc() -> dict[str, Any]:
    """A registry document with one problem of every kind.

    Returns:
        The document as a plain dict.
    """
    return {
        "version": 1,
        "setup": "broken-demo",
        "setups": "unknown root key",
        "devices": [
            {
                "type": "camera",
                "name": "BadCam",
                "pixelcount": {"x": -5},  # y missing, x out of range
                "pixelpitch_um": {"x": 3.45},
                "binning": 3,  # not in [1, 2, 4]
                "colour": "red",  # unknown key
            },
            {"type": "stage", "name": "NoAxes", "axes": []},  # min_length=1
            {"type": "spectrometer", "name": "Ghost"},  # unknown device type
            {"name": "NoType"},  # missing discriminator
            "not-an-object",
        ],
    }


def test_valid_document_has_no_errors(registry_doc: dict[str, Any]) -> None:
    """A good document produces an empty error list.

    Args:
        registry_doc: The valid multi-device document fixture.
    """
    assert validate_registry(registry_doc) == []


def test_every_problem_is_reported_once_and_precisely(broken_doc: dict[str, Any]) -> None:
    """Each entry is checked against its own sub-schema, so locations stay exact.

    Args:
        broken_doc: The deliberately broken document fixture.
    """
    errors = validate_registry(broken_doc)
    joined = "\n".join(errors)

    assert "<root>: unknown key 'setups'" in errors
    assert "devices[0].pixelcount: 'y' is a required property" in errors
    assert "devices[0].pixelcount.x: -5 is less than or equal to the minimum of 0" in errors
    assert "devices[0].binning: 3 is not one of [1, 2, 4]" in errors
    assert "colour" in joined
    assert "devices[1].axes: [] should be non-empty" in errors
    assert "devices[2]: unknown type 'spectrometer'" in joined
    assert "known: camera, filterwheel, laser, stage, unknown" in joined
    assert "devices[3]: missing 'type' discriminator" in errors
    assert "devices[4]: expected an object, got str" in errors

    # The union noise this module exists to avoid must not appear.
    assert "is not valid under any of the given schemas" not in joined


def test_single_device_file_gets_a_hint(camera_doc: dict[str, Any]) -> None:
    """Pointing the registry loader at a single-device file explains what to do.

    Args:
        camera_doc: The valid camera document fixture.
    """
    errors = validate_registry(camera_doc)
    assert len(errors) == 1
    assert "'devices' is a required property" in errors[0]
    assert "single-device file" in errors[0]


@pytest.mark.parametrize(
    ("document", "message"),
    [
        (["a", "list"], "expected a mapping"),
        ({"version": 1, "devices": "nope"}, "expected a list"),
    ],
)
def test_malformed_top_level(document: Any, message: str) -> None:  # noqa: ANN401 - by design
    """A document of the wrong shape fails before any device is looked at.

    Args:
        document: The malformed document.
        message: Fragment expected in the error message.
    """
    assert any(message in err for err in validate_registry(document))


def test_load_devices_raises_with_all_errors(
    broken_doc: dict[str, Any], write_config: ConfigWriter
) -> None:
    """The loader collects the messages into one readable exception.

    Args:
        broken_doc: The deliberately broken document fixture.
        write_config: Helper writing a document into the temporary config dir.
    """
    path = write_config(broken_doc, "Devices_broken.yml")
    with pytest.raises(DeviceConfigError) as excinfo:
        load_devices(path)

    message = str(excinfo.value)
    assert message.startswith("Devices_broken.yml failed validation:")
    assert message.count("\n  - ") >= 8


def test_device_errors_are_config_errors(write_config: ConfigWriter) -> None:
    """`DeviceConfigError` is a `ConfigError`, like the camera one.

    Args:
        write_config: Helper writing a document into the temporary config dir.
    """
    with pytest.raises(ConfigError):
        load_devices(write_config({"devices": [{"type": "stage"}]}, "bad.yaml"))


def test_unsupported_suffix_rejected(tmp_path: Path) -> None:
    """Only .json/.yaml/.yml are parsed.

    Args:
        tmp_path: Pytest's built-in temporary path fixture.
    """
    path = tmp_path / "devices.txt"
    path.write_text("devices: []", encoding="utf-8")
    with pytest.raises(DeviceConfigError, match="Unsupported file type"):
        load_devices(path)


@pytest.mark.parametrize("suffix", [".yaml", ".yml", ".json"])
def test_round_trip(registry_doc: dict[str, Any], write_config: ConfigWriter, suffix: str) -> None:
    """A registry survives being written out and read back in any format.

    Args:
        registry_doc: The valid multi-device document fixture.
        write_config: Helper writing a document into the temporary config dir.
        suffix: Output format under test.
    """
    original = load_devices(write_config(registry_doc, "Devices.yml"))
    written = dump_devices(original, f"round_trip{suffix}")

    assert load_devices(written) == original


def test_dump_keeps_the_discriminator(
    registry_doc: dict[str, Any], write_config: ConfigWriter
) -> None:
    """Every written entry keeps its `type`, or the file could not be read back.

    Args:
        registry_doc: The valid multi-device document fixture.
        write_config: Helper writing a document into the temporary config dir.
    """
    registry = load_devices(write_config(registry_doc, "Devices.yml"))
    written = json.loads(dump_devices(registry, "out.json").read_text(encoding="utf-8"))

    assert [entry["type"] for entry in written["devices"]] == [
        "camera",
        "stage",
        "laser",
        "filterwheel",
    ]


def test_describe(registry_doc: dict[str, Any], write_config: ConfigWriter) -> None:
    """`describe` prints the setup header plus one line per device.

    Args:
        registry_doc: The valid multi-device document fixture.
        write_config: Helper writing a document into the temporary config dir.
    """
    registry = load_devices(write_config(registry_doc, "Devices.yml"))
    lines = describe(registry).splitlines()

    assert lines[0] == "setup: test-bench (v1)"
    assert len(lines) == 5
    assert "1920x1200 px" in lines[1]
    assert "axes x/y" in lines[2]
    assert "488 nm, 100 mW" in lines[3]
    assert "2 slots" in lines[4]


def test_export_json_schema_defaults_to_the_schema_dir(config_dir: Path) -> None:
    """Without an argument the export lands in the managed schema directory.

    Args:
        config_dir: The temporary config directory fixture.
    """
    target = export_devices_schema()
    schema = json.loads(target.read_text(encoding="utf-8"))

    assert target == config_dir / "schemas" / "devices.schema.json"
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert "devices" in schema["properties"]
