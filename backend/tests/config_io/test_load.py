"""Tests for `load_config`: top level, device_id keys, error collection and references."""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any, Callable

import pytest

from newswitch.config_io import ConfigError, ConfigWarning, DetectorConfig, load_config

from .conftest import DocWriter


def _problems(write_doc: DocWriter, doc: Any) -> list[str]:  # noqa: ANN401
    write_doc(doc)
    with pytest.raises(ConfigError) as info:
        load_config()
    return info.value.problems


def test_loads_minimal_doc(write_doc: DocWriter, minimal_doc: dict[str, Any]) -> None:
    """A valid file yields one dataclass per entry, keyed and ordered as in the file."""
    write_doc(minimal_doc)
    config = load_config().config
    assert list(config.devices) == list(minimal_doc["devices"])
    assert isinstance(config.devices["cam"], DetectorConfig)
    assert config.devices["cam"].device_id == "cam"
    assert config.devices["cam"].exposure_time_ms.unit == "ms"


def test_explicit_path(tmp_path: Path, minimal_doc: dict[str, Any], write_doc: DocWriter) -> None:
    """An explicit path bypasses the managed directory."""
    path = write_doc(minimal_doc, "elsewhere.yml")
    assert load_config(path).path == path


def test_device_id_must_match_key(write_doc: DocWriter, minimal_doc: dict[str, Any]) -> None:
    """A stated device_id equal to the key is fine; a different one is an error."""
    minimal_doc["devices"]["cam"]["device_id"] = "cam"
    write_doc(minimal_doc)
    load_config()

    minimal_doc["devices"]["cam"]["device_id"] = "other"
    problems = _problems(write_doc, minimal_doc)
    assert problems == ["devices.cam.device_id: 'other' differs from key 'cam'"]


def test_collects_all_structural_problems(
    write_doc: DocWriter, minimal_doc: dict[str, Any]
) -> None:
    """Every problem is reported at once, each with its path in the file."""
    minimal_doc["extra"] = 1
    minimal_doc["devices"]["cam"]["pixelcount"] = [-5, 480]
    minimal_doc["devices"]["gfp"]["transmission"] = 3
    minimal_doc["devices"]["obj10"]["type"] = "lens"
    minimal_doc["devices"]["led"].pop("type")
    minimal_doc["devices"]["stage"]["axes"][0]["label"] = "q"
    problems = _problems(write_doc, minimal_doc)
    joined = "\n".join(problems)
    assert "<root>: unknown key 'extra'" in joined
    assert "devices.cam.pixelcount.0: -5 is less than or equal to the minimum of 0" in joined
    assert "devices.gfp.transmission:" in joined
    assert "devices.obj10.type: unknown device type 'lens'" in joined
    assert "devices.led: missing 'type'" in joined
    assert "devices.stage.axes.0.label:" in joined


@pytest.mark.parametrize(
    ("doc", "expected"),
    [
        ([], "<root>: expected a mapping"),
        ({"devices": {}}, "<root>: missing key 'newswitch_version'"),
        ({"newswitch_version": "v1", "devices": []}, "devices: expected a mapping"),
        ({"newswitch_version": 1, "devices": {}}, "newswitch_version: expected a string"),
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


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (lambda d: d["led"].update(controller="nope"), "devices.led.controller: no device 'nope'"),
        (lambda d: d["led"].update(controller="cam"), "'cam' is not a controller"),
        (lambda d: d["turret"]["channels"].append("missing"), "no device 'missing'"),
        (lambda d: d["turret"]["channels"].append("led"), "neither an objective nor a filter"),
        (lambda d: d["turret"]["channels"].append("gfp"), "mixes objectives and filters"),
        (lambda d: d["turret"]["channels"].append("obj10"), "'obj10' is already mounted"),
    ],
)
def test_references(
    write_doc: DocWriter,
    minimal_doc: dict[str, Any],
    change: Callable[[dict[str, Any]], None],
    expected: str,
) -> None:
    """References between devices are checked after validation."""
    change(minimal_doc["devices"])
    problems = _problems(write_doc, minimal_doc)
    assert any(expected in p for p in problems), problems


def test_shared_resource_conflict(write_doc: DocWriter, minimal_doc: dict[str, Any]) -> None:
    """Two devices on one port must agree on its settings."""
    minimal_doc["devices"]["other"] = {
        **minimal_doc["devices"]["mainboard"],
        "connection": {
            "protocol": "uc2-rest",
            "transport": {"type": "serial", "port": "/dev/ttyUSB0", "baudrate": 9600},
        },
    }
    problems = _problems(write_doc, minimal_doc)
    assert any("shared resource" in p and "baudrate" in p for p in problems)


def test_version_mismatch_warns(write_doc: DocWriter, minimal_doc: dict[str, Any]) -> None:
    """A file written for another major/minor version loads with a warning."""
    minimal_doc["newswitch_version"] = "v0.1.0-alpha.0"
    write_doc(minimal_doc)
    with pytest.warns(ConfigWarning, match="written for newswitch"):
        load_config()


def test_unconvertible_unit_warns_and_loads(
    write_doc: DocWriter, minimal_doc: dict[str, Any]
) -> None:
    """A value in an unusable unit is dropped with a warning instead of failing."""
    minimal_doc["devices"]["cam"]["exposure_time_ms"] = {"value": 1.0, "unit": "Hz"}
    write_doc(minimal_doc)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        config = load_config().config
    assert config.devices["cam"].exposure_time_ms is None
    assert any(issubclass(w.category, ConfigWarning) for w in caught)


def test_rejects_json(config_dir: Path) -> None:
    """Only YAML files are read."""
    (config_dir / "cfg.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ConfigError, match="only YAML"):
        load_config(config_dir / "cfg.json")


def test_missing_file(config_dir: Path) -> None:
    """A missing file is a ConfigError naming what was tried."""
    with pytest.raises(ConfigError, match="newswitch-config.yaml"):
        load_config()


def test_unparseable(write_doc: DocWriter) -> None:
    """Broken YAML is a ConfigError."""
    write_doc("devices: [unclosed\n")
    with pytest.raises(ConfigError, match="cannot be parsed"):
        load_config()
