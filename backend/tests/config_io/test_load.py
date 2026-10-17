"""Tests for `load_config` / `open_config`: top level, error collection, file roles."""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

import pytest

from newswitch.config_io import (
    ConfigError,
    ConfigWarning,
    DetectorConfig,
    ensure_persistent_copy,
    load_config,
    open_config,
)

from .conftest import DocWriter, get_device


def _problems(write_doc: DocWriter, doc: Any) -> list[str]:  # noqa: ANN401
    path = write_doc(doc)
    with pytest.raises(ConfigError) as info:
        load_config(path)
    return info.value.problems


def test_loads_minimal_doc(write_doc: DocWriter, minimal_doc: dict[str, Any]) -> None:
    """A valid file yields one dataclass per entry, keyed and ordered as in the file."""
    path = write_doc(minimal_doc)
    config = load_config(path).config
    assert list(config.devices) == list(minimal_doc["devices"])
    cam = config.devices["cam"]
    assert isinstance(cam, DetectorConfig)
    assert cam.name == "Cam"
    assert cam.exposure_time_ms is not None and cam.exposure_time_ms.unit == "ms"


def test_explicit_path(tmp_path: Path, minimal_doc: dict[str, Any], write_doc: DocWriter) -> None:
    """The loaded file remembers the path it was read from (and is saved to)."""
    path = write_doc(minimal_doc, "elsewhere.yml")
    assert load_config(path).path == path


def test_further_keys_are_accepted(write_doc: DocWriter, minimal_doc: dict[str, Any]) -> None:
    """Device and mapping entries may carry keys newswitch does not know yet."""
    minimal_doc["devices"]["cam"]["optikit_dsn_variable"] = "camera-1"
    minimal_doc["devices"]["cam"]["device_id"] = "no longer used"
    minimal_doc["devices"]["mainboard"]["mapping"]["cam"]["serial_number"] = "00F1"
    config = load_config(write_doc(minimal_doc)).config
    cam = get_device(config, "cam", DetectorConfig)
    assert cam.extras == {"optikit_dsn_variable": "camera-1", "device_id": "no longer used"}
    assert config.controllers[0].mapping["cam"].extras == {"serial_number": "00F1"}


def test_collects_all_structural_problems(
    write_doc: DocWriter, minimal_doc: dict[str, Any]
) -> None:
    """Every problem is reported at once, each with its path in the file."""
    minimal_doc["extra"] = 1
    minimal_doc["devices"]["cam"]["pixelcount"] = [-5, 480]
    minimal_doc["devices"]["gfp"]["transmission"] = 3
    minimal_doc["devices"]["obj10"]["type"] = "lens"
    minimal_doc["devices"]["led"].pop("type")
    minimal_doc["devices"]["ax-z"].pop("steps_per_um")
    minimal_doc["devices"]["stage"]["axes"]["y"] = 3
    minimal_doc["devices"]["mainboard"]["mapping"]["cam"]["id"] = "21,"
    problems = _problems(write_doc, minimal_doc)
    joined = "\n".join(problems)
    assert "<root>: unknown key 'extra'" in joined
    assert "devices.cam.pixelcount.0: -5 is less than or equal to the minimum of 0" in joined
    assert "devices.gfp.transmission:" in joined
    assert "devices.obj10.type: unknown device type 'lens'" in joined
    assert "devices.led: missing 'type'" in joined
    assert "devices.ax-z: 'steps_per_um' is a required property" in joined
    assert "devices.stage.axes.y: 3 is not of type 'string'" in joined
    assert "devices.mainboard.mapping.cam.id: '21,' is not of type 'integer'" in joined


@pytest.mark.parametrize(
    ("doc", "expected"),
    [
        ([], "<root>: expected a mapping"),
        ({"devices": {}}, "<root>: missing key 'newswitch_version'"),
        ({"newswitch_version": "v1", "devices": []}, "devices: expected a mapping"),
        ({"newswitch_version": 1, "devices": {}}, "newswitch_version: expected a string"),
        (
            {"newswitch_version": "v1", "devices": {}, "connections": {}},
            "<root>: unknown key 'connections'",
        ),
    ],
)
def test_top_level(write_doc: DocWriter, doc: Any, expected: str) -> None:  # noqa: ANN401
    """The top level needs exactly newswitch_version and a devices mapping."""
    assert any(p.startswith(expected) for p in _problems(write_doc, doc))


def test_pydantic_errors_use_file_paths(write_doc: DocWriter, minimal_doc: dict[str, Any]) -> None:
    """Cross-field errors from pydantic carry file paths without the type tag."""
    minimal_doc["devices"]["cam"]["exposure_time_ms"] = {"value": 5000.0, "max": 1000.0}
    problems = _problems(write_doc, minimal_doc)
    assert len(problems) == 1
    assert problems[0].startswith("devices.cam.exposure_time_ms:")


def test_version_mismatch_warns(write_doc: DocWriter, minimal_doc: dict[str, Any]) -> None:
    """A file written for another major/minor version loads with a warning."""
    minimal_doc["newswitch_version"] = "v0.1.0-alpha.0"
    path = write_doc(minimal_doc)
    with pytest.warns(ConfigWarning, match="written for newswitch"):
        load_config(path)


def test_unconvertible_unit_warns_and_loads(
    write_doc: DocWriter, minimal_doc: dict[str, Any]
) -> None:
    """A value in an unusable unit is dropped with a warning instead of failing."""
    minimal_doc["devices"]["cam"]["exposure_time_ms"] = {"value": 1.0, "unit": "Hz"}
    path = write_doc(minimal_doc)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        config = load_config(path).config
    assert get_device(config, "cam", DetectorConfig).exposure_time_ms is None
    assert any(issubclass(w.category, ConfigWarning) for w in caught)


def test_rejects_json(config_dir: Path) -> None:
    """Only YAML files are read."""
    (config_dir / "cfg.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ConfigError, match="only YAML"):
        load_config(config_dir / "cfg.json")


def test_missing_file(config_path: Path) -> None:
    """A missing file is a ConfigError naming the path."""
    with pytest.raises(ConfigError, match="newswitch-config.yaml"):
        load_config(config_path)


def test_unparseable(write_doc: DocWriter) -> None:
    """Broken YAML is a ConfigError."""
    path = write_doc("devices: [unclosed\n")
    with pytest.raises(ConfigError, match="cannot be parsed"):
        load_config(path)


def test_persistent_copy_is_made_once(write_doc: DocWriter, config_dir: Path) -> None:
    """The persistent file starts as a copy of the static one and is then left alone."""
    static = write_doc("# keep this comment\nnewswitch_version: v1.0.0\ndevices: {}\n")
    persistent = config_dir / "sub" / "persistent.yaml"

    assert ensure_persistent_copy(static, persistent) == persistent
    assert persistent.read_text(encoding="utf-8") == static.read_text(encoding="utf-8")

    persistent.write_text("changed at runtime\n", encoding="utf-8")
    ensure_persistent_copy(static, persistent)
    assert persistent.read_text(encoding="utf-8") == "changed at runtime\n"


def test_persistent_copy_needs_the_static_file(config_dir: Path) -> None:
    """Without either file there is nothing to copy."""
    with pytest.raises(ConfigError, match="static.yaml"):
        ensure_persistent_copy(config_dir / "static.yaml", config_dir / "persistent.yaml")


def test_open_config_needs_two_files(config_dir: Path, write_doc: DocWriter) -> None:
    """Static and persistent must be different files, or the static one would be written."""
    static = write_doc("newswitch_version: v1.0.0\ndevices: {}\n", "static.yaml")
    same = config_dir / "." / "static.yaml"
    with pytest.raises(ConfigError, match="same file"):
        open_config(static, same, from_static=True)


@pytest.mark.parametrize("from_static", [True, False])
def test_static_file_is_never_written(
    config_dir: Path, write_doc: DocWriter, minimal_doc: dict[str, Any], from_static: bool
) -> None:
    """save() goes to the persistent file and refuses an explicit static target."""
    static = write_doc(minimal_doc, "static.yaml")
    persistent = config_dir / "persistent.yaml"
    cfg_file = open_config(static, persistent, from_static=from_static)
    assert cfg_file.path == (static if from_static else persistent)
    assert cfg_file.target == persistent
    with pytest.raises(ConfigError, match="refusing to write the static configuration"):
        cfg_file.save(static)
    assert cfg_file.save() == persistent


def test_load_config_saves_in_place(write_doc: DocWriter, minimal_doc: dict[str, Any]) -> None:
    """A file loaded on its own is written back to itself."""
    path = write_doc(minimal_doc)
    cfg_file = load_config(path)
    assert cfg_file.target == path and cfg_file.protected is None
