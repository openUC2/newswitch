"""Tests for `newswitch.config`: where files live and how names are resolved.

`Paths` is the single place that knows the folder layout. The loaders in
`newswitch.schemas` go through `config_file()` / `schema_file()`, so the resolution
rules pinned here decide what ``load_config("Devices")`` actually opens.
"""

import os
from pathlib import Path

import pytest

from newswitch.config import CONFIG_SUFFIXES, APP_NAME, Paths, get_paths


def test_defaults_point_into_the_backend_config_folder() -> None:
    """The development defaults resolve to `backend/Configs` and its subfolders."""
    paths = Paths()

    assert paths.config_dir.name == "Configs"
    assert paths.schema_dir == paths.config_dir / "schemas"
    assert paths.data_dir == paths.config_dir / "data"
    assert paths.log_dir == paths.config_dir / "logs"
    assert paths.config_dir.is_dir(), "the sample config folder should exist in a checkout"


def test_get_paths_is_cached() -> None:
    """`get_paths` hands out one shared instance rather than re-reading the env."""
    assert get_paths() is get_paths()


FOREIGN_ENV = "BACKEND_HOST=0.0.0.0\nBACKEND_PORT=8069\nFRONTEND_PORT=5473\n"


def test_working_directory_does_not_matter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`Paths()` must not depend on where the process was started.

    The repository root holds a shared `.env` with the stack's ports. A relative
    ``env_file`` would be resolved against the working directory, so a debugger
    launched from the repo root used to read that file and crash on its entries,
    while `uv run` from `backend/` found no `.env` at all.

    Args:
        tmp_path: Pytest's built-in temporary path fixture.
        monkeypatch: Pytest's environment patcher.
    """
    (tmp_path / ".env").write_text(FOREIGN_ENV, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert Paths().config_dir.name == "Configs"


def test_foreign_env_file_entries_are_ignored(tmp_path: Path) -> None:
    """Variables of the shared `.env` that are not settings must be ignored.

    With `extra="forbid"` — the `BaseSettings` default — pydantic-settings hands every
    entry of the dotenv file to the model unchanged, prefix or not, and the model then
    rejects them as extra inputs.

    Args:
        tmp_path: Pytest's built-in temporary path fixture.
    """
    env_file = tmp_path / ".env"
    env_file.write_text(FOREIGN_ENV, encoding="utf-8")

    paths = Paths(_env_file=env_file)  # type: ignore[call-arg]

    assert paths.config_dir.name == "Configs"


def test_env_file_can_still_set_a_field(tmp_path: Path) -> None:
    """Ignoring foreign keys must not stop a NEWSWITCH_* entry from being read.

    Args:
        tmp_path: Pytest's built-in temporary path fixture.
    """
    env_file = tmp_path / ".env"
    env_file.write_text(f"{FOREIGN_ENV}NEWSWITCH_CONFIG_DIR={tmp_path / 'own'}\n", encoding="utf-8")

    paths = Paths(_env_file=env_file)  # type: ignore[call-arg]

    assert paths.config_dir == tmp_path / "own"


def test_environment_overrides(config_dir: Path) -> None:
    """Each directory can be redirected with its own NEWSWITCH_* variable.

    Args:
        config_dir: The temporary config directory fixture.
    """
    paths = get_paths()

    assert paths.config_dir == config_dir
    assert paths.schema_dir == config_dir / "schemas"
    assert paths.data_dir == config_dir / "data"


def test_app_name_and_suffixes() -> None:
    """The supported extensions are tried in this order for a name without one."""
    assert APP_NAME == "newswitch"
    assert CONFIG_SUFFIXES == (".yaml", ".yml", ".json")


def test_device_settings_file(config_dir: Path) -> None:
    """The device settings file is named relative to the config directory.

    Args:
        config_dir: The temporary config directory fixture.
    """
    assert get_paths().device_settings_file == config_dir / "uc2DevSettings.json"


def test_config_file_with_suffix(config_dir: Path) -> None:
    """A bare name with a known suffix is looked up in the config directory.

    Args:
        config_dir: The temporary config directory fixture.
    """
    (config_dir / "Devices.yml").write_text("devices: []", encoding="utf-8")
    assert get_paths().config_file("Devices.yml") == config_dir / "Devices.yml"


@pytest.mark.parametrize("suffix", [".yaml", ".yml", ".json"])
def test_config_file_without_suffix(config_dir: Path, suffix: str) -> None:
    """A name without a suffix finds whichever supported extension exists.

    Args:
        config_dir: The temporary config directory fixture.
        suffix: The extension the file is written with.
    """
    (config_dir / f"Devices{suffix}").write_text("devices: []", encoding="utf-8")
    assert get_paths().config_file("Devices").suffix == suffix


def test_config_file_prefers_yaml_over_json(config_dir: Path) -> None:
    """With several candidates present, `CONFIG_SUFFIXES` decides the winner.

    Args:
        config_dir: The temporary config directory fixture.
    """
    for suffix in (".yaml", ".yml", ".json"):
        (config_dir / f"Devices{suffix}").write_text("devices: []", encoding="utf-8")
    assert get_paths().config_file("Devices").suffix == ".yaml"


def test_config_file_passes_explicit_paths_through(config_dir: Path, tmp_path: Path) -> None:
    """A path with a directory part is never rewritten into the managed folder.

    Args:
        config_dir: The temporary config directory fixture.
        tmp_path: Pytest's built-in temporary path fixture.
    """
    outside = tmp_path / "outside.yaml"
    outside.write_text("devices: []", encoding="utf-8")

    assert get_paths().config_file(outside) == outside
    assert get_paths().config_file(Path("./missing/file.yaml"), must_exist=False) == Path(
        "./missing/file.yaml"
    )


def test_config_file_missing_lists_candidates(config_dir: Path) -> None:
    """The error names every candidate, which is what makes a typo obvious.

    Args:
        config_dir: The temporary config directory fixture.
    """
    with pytest.raises(FileNotFoundError) as excinfo:
        get_paths().config_file("Devices")

    message = str(excinfo.value)
    assert "Devices.yaml" in message and "Devices.yml" in message and "Devices.json" in message


def test_config_file_for_writing(config_dir: Path) -> None:
    """`must_exist=False` yields the canonical target for a file yet to be written.

    Args:
        config_dir: The temporary config directory fixture.
    """
    target = get_paths().config_file("new.yml", must_exist=False)
    assert target == config_dir / "new.yml"
    assert not target.exists()

    # Without a suffix the first supported extension is the canonical choice.
    assert get_paths().config_file("new", must_exist=False) == config_dir / "new.yaml"


def test_schema_file(config_dir: Path) -> None:
    """Schema names resolve against `schema_dir` and default to write mode.

    Args:
        config_dir: The temporary config directory fixture.
    """
    schemas = config_dir / "schemas"
    schemas.mkdir()

    assert get_paths().schema_file("camera.schema.json") == schemas / "camera.schema.json"

    with pytest.raises(FileNotFoundError):
        get_paths().schema_file("camera.schema.json", must_exist=True)


def test_ensure_writable_dirs_creates_them(config_dir: Path) -> None:
    """Data, log and schema directories are created on demand.

    Args:
        config_dir: The temporary config directory fixture.
    """
    paths = get_paths()
    assert not paths.data_dir.exists()

    paths.ensure_writable_dirs()

    assert paths.data_dir.is_dir()
    assert paths.log_dir.is_dir()
    assert paths.schema_dir.is_dir()


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_ensure_writable_dirs_reports_a_read_only_directory(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A directory that exists but cannot be written to is a deployment error.

    Args:
        config_dir: The temporary config directory fixture.
        monkeypatch: Pytest's environment patcher.
    """
    read_only = config_dir / "read_only"
    read_only.mkdir()
    read_only.chmod(0o500)
    monkeypatch.setenv("NEWSWITCH_DATA_DIR", str(read_only / "data"))
    get_paths.cache_clear()

    try:
        with pytest.raises(RuntimeError, match="Cannot create"):
            get_paths().ensure_writable_dirs()
    finally:
        read_only.chmod(0o700)
