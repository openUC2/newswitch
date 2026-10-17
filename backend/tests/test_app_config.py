"""Tests for `ImswitchConfig`: the settings read from ``backend/base_config.yaml``.

Apart from the first test, `BASE_CONFIG_FILE` is pointed at a temporary file, so each
test decides the content itself.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pytest
import yaml
from pydantic import ValidationError

import newswitch.app as app_module
from newswitch.app import BASE_CONFIG_FILE, ImswitchConfig

BASE: dict[str, Any] = {
    "use_virtual_microscope": True,
    "db_path": "agent_data.db",
    "available_cubes": ["cube1", "cube2"],
    "config_dir": "Configs",
    "schema_dir": "Configs/schemas",
    "static_config_path": "static.yaml",
    "persistent_config_path": "persistent.yaml",
    "load_from_static_config_path": True,
}

# (key=value changes to BASE) -> path of the written base config
BaseWriter = Callable[..., Path]


@pytest.fixture
def write_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> BaseWriter:
    """Return a helper that writes a base config and makes `ImswitchConfig` read it.

    Args:
        tmp_path: Pytest's built-in temporary path fixture.
        monkeypatch: Pytest's patcher; restores `BASE_CONFIG_FILE` afterwards.

    Returns:
        A callable taking keyword changes to `BASE`.
    """

    def _write(**changes: object) -> Path:
        path = tmp_path / "base" / "base_config.yaml"
        path.parent.mkdir(exist_ok=True)
        path.write_text(yaml.safe_dump({**BASE, **changes}), encoding="utf-8")
        monkeypatch.setattr(app_module, "BASE_CONFIG_FILE", path)
        return path

    return _write


def test_shipped_base_config_loads() -> None:
    """The committed base_config.yaml is complete and points at the shipped device file."""
    settings = ImswitchConfig()
    assert settings.config_dir == BASE_CONFIG_FILE.parent / "Configs"
    assert settings.schema_dir == settings.config_dir / "schemas"
    assert settings.static_config_path == settings.config_dir / "newswitch-config.yaml"
    assert settings.static_config_path.is_file()
    assert settings.config_file in (settings.static_config_path, settings.persistent_config_path)


def test_values_come_from_the_file(write_base: BaseWriter) -> None:
    """Every setting is taken from the file."""
    write_base(use_virtual_microscope=False, db_path="other.db", available_cubes=["c"])
    settings = ImswitchConfig()
    assert settings.use_virtual_microscope is False
    assert settings.db_path == "other.db"
    assert settings.available_cubes == ["c"]


def test_static_or_persistent(write_base: BaseWriter) -> None:
    """`load_from_static_config_path` decides which device file is used."""
    base = write_base()
    assert ImswitchConfig().config_file == base.parent / "Configs" / "static.yaml"

    write_base(load_from_static_config_path=False)
    assert ImswitchConfig().config_file == base.parent / "Configs" / "persistent.yaml"


def test_keyword_arguments_override_the_file(write_base: BaseWriter) -> None:
    """``config_file=None`` (the tests' virtual devices) wins over the file."""
    write_base()
    assert ImswitchConfig(config_file=None).config_file is None
    assert ImswitchConfig(db_path="x.db").db_path == "x.db"


def test_relative_dirs_follow_the_base_file(
    write_base: BaseWriter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Relative folders hang off the base config's folder, not the working directory."""
    base = write_base()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    settings = ImswitchConfig()
    assert settings.config_dir == base.parent / "Configs"
    assert settings.schema_dir == base.parent / "Configs" / "schemas"


def test_explicit_paths_are_kept(write_base: BaseWriter, tmp_path: Path) -> None:
    """Absolute paths and paths with a directory part are used as given."""
    write_base(
        config_dir=str(tmp_path / "abs"),
        static_config_path=str(tmp_path / "devices.yaml"),
        persistent_config_path="sub/persistent.yaml",
    )
    settings = ImswitchConfig()
    assert settings.config_dir == tmp_path / "abs"
    assert settings.static_config_path == tmp_path / "devices.yaml"
    assert settings.persistent_config_path == Path("sub/persistent.yaml")


def test_unknown_key_is_an_error(write_base: BaseWriter) -> None:
    """A misspelled key is reported instead of silently ignored."""
    write_base(use_virutal_microscope=True)
    with pytest.raises(ValidationError, match="use_virutal_microscope"):
        ImswitchConfig()


def test_missing_key_is_an_error(write_base: BaseWriter) -> None:
    """There are no built-in defaults: every key must be in the file."""
    path = write_base()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    del data["db_path"]
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ValidationError, match="db_path"):
        ImswitchConfig()


def test_missing_base_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without the base config newswitch refuses to start."""
    monkeypatch.setattr(app_module, "BASE_CONFIG_FILE", tmp_path / "base_config.yaml")
    with pytest.raises(FileNotFoundError, match="base_config.yaml"):
        ImswitchConfig()


def test_environment_is_ignored(write_base: BaseWriter, monkeypatch: pytest.MonkeyPatch) -> None:
    """Environment variables do not override the file."""
    write_base()
    monkeypatch.setenv("DB_PATH", "from-env.db")
    assert ImswitchConfig().db_path == "agent_data.db"
