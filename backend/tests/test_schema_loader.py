"""Tests for `loader`: one entry point for every config layout.

`load_config` has to turn four document shapes — registry mapping, bare list, single
device with a `type`, single device without one — into the same `DeviceRegistry`, in
JSON and YAML alike, whether it is handed a path or a bare name.
"""

from pathlib import Path
from typing import Any

import pytest

from newswitch.schemas import (
    CameraDevice,
    ConfigError,
    DeviceRegistry,
    LaserDevice,
    StageDevice,
    UnknownDevice,
    dump_config,
    load_config,
    load_device,
)
from tests.conftest import ConfigWriter


def test_registry_file(registry_doc: dict[str, Any], write_config: ConfigWriter) -> None:
    """A multi-device file loads as the registry it describes.

    Args:
        registry_doc: The valid multi-device document fixture.
        write_config: Helper writing a document into the temporary config dir.
    """
    registry = load_config(write_config(registry_doc, "Devices.yml"))

    assert isinstance(registry, DeviceRegistry)
    assert len(registry.devices) == 4
    assert registry.setup == "test-bench"


def test_single_device_file_is_wrapped(
    camera_doc: dict[str, Any], write_config: ConfigWriter
) -> None:
    """A single-device file yields a one-entry registry, not a special case.

    Args:
        camera_doc: The valid camera document fixture.
        write_config: Helper writing a document into the temporary config dir.
    """
    registry = load_config(write_config(camera_doc, "cam.yaml"))

    assert len(registry.devices) == 1
    assert isinstance(registry.devices[0], CameraDevice)
    assert registry.version == 1
    assert registry.setup is None


def test_typeless_single_device_file_becomes_opaque(
    camera_doc: dict[str, Any], write_config: ConfigWriter
) -> None:
    """Without a `type` key there is nothing to dispatch on, so nothing is validated.

    No device model defaults its discriminator, so `DEFAULT_DEVICE_TYPE` applies and
    the entry is kept as an opaque `UnknownDevice`: its fields survive the round-trip
    but none of them are checked.

    Args:
        camera_doc: The valid camera document fixture.
        write_config: Helper writing a document into the temporary config dir.
    """
    typeless = {k: v for k, v in camera_doc.items() if k != "type"}
    registry = load_config(write_config(typeless, "cam.yaml"))

    device = registry.devices[0]
    assert isinstance(device, UnknownDevice)
    assert device.payload["pixelcount"] == {"x": 1920, "y": 1200}


def test_a_typo_in_type_is_caught_but_an_omission_is_not(
    write_config: ConfigWriter,
) -> None:
    """The asymmetry that `DEFAULT_DEVICE_TYPE = "unknown"` buys, pinned deliberately.

    A misspelled discriminator is rejected — that is what catches `stagee`. An
    *omitted* one cannot be told apart from a device this version does not model, so
    it is accepted as opaque payload instead. Validation is lost silently, which is
    the price of being able to hold a config written by a newer build.

    Args:
        write_config: Helper writing a document into the temporary config dir.
    """
    stage_doc = {
        "type": "stage",
        "name": "XY-Test",
        "device_id": "stage-001",
        "axes": [{"label": "x", "travel_um": 1000.0, "steps_per_um": 8.0}],
    }
    registry = load_config(write_config(stage_doc, "stage.yaml"))
    assert isinstance(registry.devices[0], StageDevice)

    with pytest.raises(ConfigError, match="unknown type 'stagee'"):
        load_config(write_config({**stage_doc, "type": "stagee"}, "typo.yaml"))

    del stage_doc["type"]
    registry = load_config(write_config(stage_doc, "typeless.yaml"))
    assert isinstance(registry.devices[0], UnknownDevice)


def test_bare_device_list(registry_doc: dict[str, Any], write_config: ConfigWriter) -> None:
    """A file holding just the list of devices, without the wrapper, is accepted.

    Args:
        registry_doc: The valid multi-device document fixture.
        write_config: Helper writing a document into the temporary config dir.
    """
    registry = load_config(write_config(registry_doc["devices"], "bare_list.yaml"))
    assert len(registry.devices) == 4


def test_devices_key_wins_over_device_fields(
    registry_doc: dict[str, Any], write_config: ConfigWriter
) -> None:
    """A document with both `devices` and `name` is a registry, not a device.

    Args:
        registry_doc: The valid multi-device document fixture.
        write_config: Helper writing a document into the temporary config dir.
    """
    registry_doc["setup"] = "named-setup"
    registry = load_config(write_config(registry_doc, "both.yaml"))
    assert len(registry.devices) == 4


@pytest.mark.parametrize("name", ["Devices.yml", "Devices", "Devices.json"])
def test_name_resolution(
    registry_doc: dict[str, Any], write_config: ConfigWriter, name: str
) -> None:
    """Bare names resolve against the config dir, with or without a suffix.

    Args:
        registry_doc: The valid multi-device document fixture.
        write_config: Helper writing a document into the temporary config dir.
        name: The name handed to the loader.
    """
    write_config(registry_doc, "Devices.yml")
    write_config(registry_doc, "Devices.json")
    assert len(load_config(name).devices) == 4


def test_explicit_path_bypasses_the_config_dir(
    registry_doc: dict[str, Any], write_config: ConfigWriter, tmp_path: Path
) -> None:
    """A path with a directory part is used as given, outside the managed folder.

    Args:
        registry_doc: The valid multi-device document fixture.
        write_config: Helper writing a document into the temporary config dir.
        tmp_path: Pytest's built-in temporary path fixture.
    """
    write_config(registry_doc, "Devices.yml")  # decoy in the config dir

    elsewhere = tmp_path / "elsewhere" / "Devices.yml"
    elsewhere.parent.mkdir()
    elsewhere.write_text("devices: []\nsetup: other\n", encoding="utf-8")

    assert load_config(elsewhere).setup == "other"


def test_missing_file_lists_the_candidates() -> None:
    """A name that resolves to nothing reports every extension it tried."""
    with pytest.raises(ConfigError) as excinfo:
        load_config("no_such_setup")

    message = str(excinfo.value)
    assert ".yaml" in message and ".yml" in message and ".json" in message


def test_single_device_errors_drop_the_index_prefix(write_config: ConfigWriter) -> None:
    """Errors of a wrapped file read the way the file looks, without `devices[0]`.

    Args:
        write_config: Helper writing a document into the temporary config dir.
    """
    path = write_config(
        {
            "type": "camera",
            "name": "BadCam",
            "pixelcount": {"x": -5},
            "pixelpitch_um": {"x": 3.45},
            "colour": "red",
        },
        "badcam.yaml",
    )
    with pytest.raises(ConfigError) as excinfo:
        load_config(path)

    message = str(excinfo.value)
    assert "devices[0]" not in message
    assert "pixelcount.x: -5 is less than or equal to the minimum of 0" in message
    assert "<root>: Additional properties are not allowed ('colour' was unexpected)" in message


def test_registry_errors_keep_the_index_prefix(
    registry_doc: dict[str, Any], write_config: ConfigWriter
) -> None:
    """Multi-device files still say which entry is at fault.

    Args:
        registry_doc: The valid multi-device document fixture.
        write_config: Helper writing a document into the temporary config dir.
    """
    registry_doc["devices"][1]["axes"] = []
    with pytest.raises(ConfigError, match=r"devices\[1\].axes"):
        load_config(write_config(registry_doc, "Devices.yml"))


def test_non_mapping_document_rejected(write_config: ConfigWriter) -> None:
    """A scalar at the top level is neither a device nor a registry.

    Args:
        write_config: Helper writing a document into the temporary config dir.
    """
    path = write_config("just a string", "scalar.yaml")
    with pytest.raises(ConfigError, match="expected a mapping or a list"):
        load_config(path)


def test_load_device_from_a_single_device_file(
    camera_doc: dict[str, Any], write_config: ConfigWriter
) -> None:
    """With exactly one device in the file, no key is needed.

    Args:
        camera_doc: The valid camera document fixture.
        write_config: Helper writing a document into the temporary config dir.
    """
    write_config(camera_doc, "testcam.yaml")
    camera = load_device("testcam")

    assert isinstance(camera, CameraDevice)
    assert camera.sensor_size_mm == pytest.approx((19.2, 12.0))


def test_load_device_by_key(registry_doc: dict[str, Any], write_config: ConfigWriter) -> None:
    """Out of a registry, the key selects the device — by id or by name.

    Args:
        registry_doc: The valid multi-device document fixture.
        write_config: Helper writing a document into the temporary config dir.
    """
    write_config(registry_doc, "Devices.yml")

    assert isinstance(load_device("Devices.yml", "laser-001"), LaserDevice)
    assert isinstance(load_device("Devices.yml", "LD-488"), LaserDevice)
    assert load_device("Devices.yml", "testcam-001").name == "TestCam-2000"


def test_load_device_without_key_is_ambiguous(
    registry_doc: dict[str, Any], write_config: ConfigWriter
) -> None:
    """Several devices and no key is an error that lists the available keys.

    Args:
        registry_doc: The valid multi-device document fixture.
        write_config: Helper writing a document into the temporary config dir.
    """
    write_config(registry_doc, "Devices.yml")
    with pytest.raises(ConfigError) as excinfo:
        load_device("Devices.yml")

    message = str(excinfo.value)
    assert "holds 4 devices" in message
    assert "laser-001" in message


def test_load_device_unknown_key(registry_doc: dict[str, Any], write_config: ConfigWriter) -> None:
    """An unknown key is reported together with what is actually in the file.

    Args:
        registry_doc: The valid multi-device document fixture.
        write_config: Helper writing a document into the temporary config dir.
    """
    write_config(registry_doc, "Devices.yml")
    with pytest.raises(ConfigError, match="no device 'nope'"):
        load_device("Devices.yml", "nope")


def test_load_device_expect_type(registry_doc: dict[str, Any], write_config: ConfigWriter) -> None:
    """`expect` turns a wrong device type into an error at the load site.

    Args:
        registry_doc: The valid multi-device document fixture.
        write_config: Helper writing a document into the temporary config dir.
    """
    write_config(registry_doc, "Devices.yml")

    assert load_device("Devices.yml", "testcam-001", expect="camera").type == "camera"

    with pytest.raises(ConfigError, match="is a laser, expected a camera"):
        load_device("Devices.yml", "laser-001", expect="camera")

    with pytest.raises(ConfigError, match="unknown device type 'spectrometer'"):
        load_device("Devices.yml", "laser-001", expect="spectrometer")


@pytest.mark.parametrize("suffix", [".yaml", ".yml", ".json"])
def test_dump_config_round_trips_a_registry(
    registry_doc: dict[str, Any], write_config: ConfigWriter, suffix: str
) -> None:
    """A registry can be stored in any supported format and read back unchanged.

    Args:
        registry_doc: The valid multi-device document fixture.
        write_config: Helper writing a document into the temporary config dir.
        suffix: Output format under test.
    """
    registry = load_config(write_config(registry_doc, "Devices.yml"))
    written = dump_config(registry, f"copy{suffix}")

    assert load_config(written) == registry


def test_dump_config_stores_a_bare_name_in_the_config_dir(
    registry_doc: dict[str, Any], write_config: ConfigWriter, config_dir: Path
) -> None:
    """Writing follows the same folder rules as reading.

    Args:
        registry_doc: The valid multi-device document fixture.
        write_config: Helper writing a document into the temporary config dir.
        config_dir: The temporary config directory fixture.
    """
    registry = load_config(write_config(registry_doc, "Devices.yml"))
    assert dump_config(registry, "backup.yml") == config_dir / "backup.yml"


def test_dump_config_stores_a_single_device(
    camera_doc: dict[str, Any], write_config: ConfigWriter
) -> None:
    """A camera is stored as a single-device file and reloads as one.

    Args:
        camera_doc: The valid camera document fixture.
        write_config: Helper writing a document into the temporary config dir.
    """
    camera = load_device(write_config(camera_doc, "cam.yaml"))
    written = dump_config(camera, "camera_copy.yaml")

    assert load_device(written) == camera


def test_dump_config_wraps_a_non_camera_device(
    registry_doc: dict[str, Any], write_config: ConfigWriter
) -> None:
    """Other device types have no single-device writer, so they get a registry file.

    Args:
        registry_doc: The valid multi-device document fixture.
        write_config: Helper writing a document into the temporary config dir.
    """
    write_config(registry_doc, "Devices.yml")
    stage = load_device("Devices.yml", "stage-001")
    written = dump_config(stage, "stage_only.yaml")

    assert load_device(written) == stage


def test_dump_config_rejects_other_objects() -> None:
    """Handing `dump_config` something that is not a device fails clearly."""
    with pytest.raises(ConfigError, match="cannot store"):
        dump_config(CameraDevice.model_json_schema(), "nope.yaml")  # type: ignore[arg-type]
