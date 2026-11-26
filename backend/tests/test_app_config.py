"""Tests for `Settings`: the ``settings`` section of the description ``NEWSWITCH_CONFIG`` names."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from newswitch.instrument import spec
from newswitch.settings import BACKEND_DIR, CONFIG_ENV_VAR, load_devices, load_settings

FAKE = BACKEND_DIR / "instruments" / "fake-microscope"


def edited(tmp_path: Path, **changes: Any) -> Path:  # noqa: ANN401
    """The fake microscope with `changes` to its ``settings``; None removes a key."""
    copy = tmp_path / "instrument"
    shutil.copytree(FAKE, copy)
    path = copy / spec.DESCRIPTION
    data = yaml.safe_load(path.read_text())
    for key, value in changes.items():
        if value is None:
            del data["settings"][key]
        else:
            data["settings"][key] = value
    path.write_text(yaml.safe_dump(data))
    return copy


def test_they_come_from_the_description() -> None:
    """Everything, with relative folders below backend/ and the description remembered."""
    settings = load_settings(str(FAKE))
    assert settings.instrument == FAKE
    assert settings.simulate == "everything"
    assert settings.db_path == "arkitekt_agent.db"
    assert settings.image_dir == Path("/tmp/newswitch/images")
    assert settings.camera_recording_dir == BACKEND_DIR / "data" / "recordings"


def test_the_environment_names_the_instrument(monkeypatch: pytest.MonkeyPatch) -> None:
    """Relative to backend/, whatever the working directory."""
    monkeypatch.setenv(CONFIG_ENV_VAR, "instruments/cam-test/microscope.yml")
    monkeypatch.chdir("/")
    settings = load_settings()
    assert settings.instrument == BACKEND_DIR / "instruments" / "cam-test" / "microscope.yml"
    assert settings.simulate == "unwired"
    instrument = load_devices(settings)
    assert instrument is not None and instrument.name == "cam-test"


def test_without_a_name_it_does_not_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """There is no default microscope to fall back on."""
    monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
    with pytest.raises(spec.SpecError, match=CONFIG_ENV_VAR):
        load_settings()


def test_a_missing_file_is_said(tmp_path: Path) -> None:
    """Rather than a traceback about reading it."""
    with pytest.raises(spec.SpecError, match="does not exist"):
        load_settings(str(tmp_path / "microscope.yml"))


def test_absolute_folders_are_kept(tmp_path: Path) -> None:
    """Used as given."""
    settings = load_settings(str(edited(tmp_path, cache_dir=str(tmp_path / "cache"))))
    assert settings.cache_dir == tmp_path / "cache"


def test_no_recording_folder_can_be_stated(tmp_path: Path) -> None:
    """null is stated: uc2_cam_py's own default."""
    copy = edited(tmp_path)
    path = copy / spec.DESCRIPTION
    data = yaml.safe_load(path.read_text())
    data["settings"]["camera_recording_dir"] = None
    path.write_text(yaml.safe_dump(data))
    assert load_settings(str(copy)).camera_recording_dir is None


def test_unknown_key_is_an_error(tmp_path: Path) -> None:
    """A misspelled key is reported instead of silently ignored."""
    with pytest.raises(spec.SpecError, match="simulatee"):
        load_settings(str(edited(tmp_path, simulatee="everything")))


@pytest.mark.parametrize(
    "key",
    [
        "simulate",
        "db_path",
        "image_dir",
        "cache_dir",
        "calibration_dir",
        "camera_recording_dir",
    ],
)
def test_missing_key_is_an_error(tmp_path: Path, key: str) -> None:
    """There are no built-in defaults: every key must be in the file."""
    with pytest.raises(spec.SpecError, match=key):
        load_settings(str(edited(tmp_path, **{key: None})))


def test_what_to_simulate_is_one_of_three(tmp_path: Path) -> None:
    """``true`` is no way to say what has no hardware."""
    with pytest.raises(spec.SpecError, match="simulate"):
        load_settings(str(edited(tmp_path, simulate=True)))


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("persistent_config_path", "persistent.yaml"),  # there is one file
        ("camera_debug_window", True),  # moved to sys_config.yaml
    ],
)
def test_the_old_settings_are_refused(tmp_path: Path, key: str, value: Any) -> None:  # noqa: ANN401
    """A key that is no longer one of the description's is an error that names it, not ignored."""
    with pytest.raises(spec.SpecError, match=key):
        load_settings(str(edited(tmp_path, **{key: value})))
