"""Tests for `camera_io`: the camera-only loader, writer and schema exporter.

The point of this module is the two-layer split. The jsonschema pass reports every
structural problem at once; the Pydantic pass adds the cross-field rules and the
derived defaults that JSON Schema cannot express. Both layers must accept the same
documents, in JSON and in YAML alike.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from newswitch.schemas import (
    CameraConfigError,
    CameraSchema,
    ConfigError,
    dump_camera,
    export_camera_schema,
    load_camera,
    read_document,
    schema_errors,
)
from tests.conftest import ConfigWriter


def test_yaml_and_json_produce_the_same_model(
    camera_doc: dict[str, Any], write_config: ConfigWriter
) -> None:
    """The format only picks the parser; the resulting model is identical.

    Args:
        camera_doc: The valid camera document fixture.
        write_config: Helper writing a document into the temporary config dir.
    """
    as_yaml = load_camera(write_config(camera_doc, "cam.yaml"))
    as_yml = load_camera(write_config(camera_doc, "cam.yml"))
    as_json = load_camera(write_config(camera_doc, "cam.json"))

    assert as_yaml == as_json == as_yml


def test_bare_name_is_resolved_against_the_config_dir(
    camera_doc: dict[str, Any], write_config: ConfigWriter
) -> None:
    """A name without a directory — and even without a suffix — is looked up.

    Args:
        camera_doc: The valid camera document fixture.
        write_config: Helper writing a document into the temporary config dir.
    """
    write_config(camera_doc, "testcam.yaml")
    assert load_camera("testcam").name == "TestCam-2000"
    assert load_camera("testcam.yaml").name == "TestCam-2000"


def test_missing_file_reports_what_it_tried() -> None:
    """A name that resolves to nothing names the candidates it looked for."""
    with pytest.raises(CameraConfigError, match="tried:"):
        load_camera("does-not-exist")


def test_unsupported_suffix_rejected(tmp_path: Path) -> None:
    """Only .json/.yaml/.yml are parsed; anything else is refused up front.

    Args:
        tmp_path: Pytest's built-in temporary path fixture.
    """
    path = tmp_path / "camera.txt"
    path.write_text("name: nope", encoding="utf-8")
    with pytest.raises(CameraConfigError, match="Unsupported file type"):
        load_camera(path)


def test_top_level_must_be_a_mapping(write_config: ConfigWriter) -> None:
    """A camera file describes one camera, so a list at the top level is an error.

    Args:
        write_config: Helper writing a document into the temporary config dir.
    """
    with pytest.raises(CameraConfigError, match="expected a mapping"):
        load_camera(write_config([{"name": "Cam"}], "list.yaml"))


def test_camera_errors_are_config_errors(write_config: ConfigWriter) -> None:
    """`CameraConfigError` is a `ConfigError`, so callers can catch just the base.

    Args:
        write_config: Helper writing a document into the temporary config dir.
    """
    with pytest.raises(ConfigError):
        load_camera(write_config({"name": "Incomplete"}, "bad.yaml"))


def test_schema_errors_lists_every_structural_problem(camera_doc: dict[str, Any]) -> None:
    """The jsonschema pass reports all violations at once, not just the first.

    Args:
        camera_doc: The valid camera document fixture.
    """
    assert schema_errors(camera_doc) == []

    broken = {**camera_doc, "pixelpitch_um": {"x": -1.0}, "binning": 3, "colour": "red"}
    del broken["name"]
    messages = schema_errors(broken)

    assert len(messages) >= 4
    joined = "\n".join(messages)
    assert "'name' is a required property" in joined
    assert "pixelpitch_um.x" in joined
    assert "binning" in joined
    assert "colour" in joined


def test_pydantic_layer_catches_what_jsonschema_cannot(
    camera_doc: dict[str, Any], write_config: ConfigWriter
) -> None:
    """An oversized ROI is structurally valid but rejected by the model.

    `minimum`/`maximum` in JSON Schema are global constants and cannot refer to
    another field, so "the ROI fits inside this sensor" only exists in Pydantic.
    With `strict_schema=False` the jsonschema pass is skipped entirely and the
    model still has to reject the file.

    Args:
        camera_doc: The valid camera document fixture.
        write_config: Helper writing a document into the temporary config dir.
    """
    # A list, not a tuple: jsonschema validates parsed documents, and a Python tuple
    # is not a JSON array to it. Feed it what the parser produces.
    camera_doc["roi"] = [0, 0, 4096, 4096]
    path = write_config(camera_doc, "oversized_roi.yaml")

    assert schema_errors(read_document(path)) == []
    with pytest.raises(CameraConfigError, match="exceeds sensor pixelcount"):
        load_camera(path, strict_schema=False)


@pytest.mark.parametrize("suffix", [".yaml", ".yml", ".json"])
def test_round_trip(camera_doc: dict[str, Any], write_config: ConfigWriter, suffix: str) -> None:
    """A loaded camera can be written back and reloaded unchanged.

    Args:
        camera_doc: The valid camera document fixture.
        write_config: Helper writing a document into the temporary config dir.
        suffix: Output format under test.
    """
    original = load_camera(write_config(camera_doc, "cam.yaml"))
    written = dump_camera(original, f"round_trip{suffix}")

    assert written.exists()
    assert load_camera(written) == original


def test_dump_fills_in_the_derived_values(
    camera_doc: dict[str, Any], write_config: ConfigWriter
) -> None:
    """Storing writes the resolved model, so derived fields become explicit.

    Args:
        camera_doc: The valid camera document fixture.
        write_config: Helper writing a document into the temporary config dir.
    """
    camera = load_camera(write_config(camera_doc, "cam.yaml"))
    written = json.loads(dump_camera(camera, "resolved.json").read_text(encoding="utf-8"))

    assert written["pixelpitch_um"] == {"x": 10.0, "y": 10.0}  # y was omitted in the source
    assert written["pixelsize_um"] == {"x": 10.0, "y": 10.0}  # whole object was omitted
    assert written["type"] == "camera"


def test_dump_rejects_unsupported_suffix(
    camera_doc: dict[str, Any], write_config: ConfigWriter, tmp_path: Path
) -> None:
    """Writing to an unknown extension fails instead of guessing a format.

    Args:
        camera_doc: The valid camera document fixture.
        write_config: Helper writing a document into the temporary config dir.
        tmp_path: Pytest's built-in temporary path fixture.
    """
    camera = load_camera(write_config(camera_doc, "cam.yaml"))
    with pytest.raises(CameraConfigError, match="Unsupported file type"):
        dump_camera(camera, tmp_path / "camera.txt")


def test_export_json_schema(tmp_path: Path) -> None:
    """The exported schema is valid JSON and declares the draft it follows.

    Args:
        tmp_path: Pytest's built-in temporary path fixture.
    """
    target = export_camera_schema(tmp_path / "camera.schema.json")
    schema = json.loads(target.read_text(encoding="utf-8"))

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["properties"].keys() >= {"name", "pixelcount", "pixelpitch_um"}
    assert schema["required"] == CameraSchema.model_json_schema()["required"]


def test_export_json_schema_defaults_to_the_schema_dir(config_dir: Path) -> None:
    """Without an argument the export lands in the managed schema directory.

    Args:
        config_dir: The temporary config directory fixture.
    """
    target = export_camera_schema()
    assert target == config_dir / "schemas" / "camera.schema.json"
    assert target.is_file()
