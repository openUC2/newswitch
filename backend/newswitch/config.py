"""
General configuration for newswitch, including paths to config, data, and log directories.

For now (24.08.2026) simply hard coded paths.

Todo: -> below
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from platformdirs import user_config_path, user_data_path, user_log_path
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_NAME = "newswitch"

# Extensions understood by the config loaders, in the order they are tried when a
# name is given without one.
CONFIG_SUFFIXES = (".yaml", ".yml", ".json")

# Repository root, derived from this module's location rather than from the working
# directory, so the same .env is read no matter where the process was started.
# Outside a checkout the files simply do not exist and are skipped.
_REPO_ROOT = Path(__file__).parent.parent.parent


def _systemd_dir(env_var: str) -> Path | None:
    # systemd may pass a colon-separated list; the first entry is ours.
    raw = os.environ.get(env_var)
    return Path(raw.split(":")[0]) if raw else None


def _resolve(name: Path, folder: Path, *, must_exist: bool) -> Path:
    """Resolve a bare file name against `folder`; pass explicit paths through.

    A name that is absolute or carries a directory part is taken as-is. A bare name
    keeps its suffix if it has one, otherwise every entry of `CONFIG_SUFFIXES` is
    tried in order and the first existing candidate wins.

    Args:
        name: The name or path to resolve.
        folder: Managed directory a bare name is resolved against.
        must_exist: Raise instead of returning a path that does not exist.

    Returns:
        The resolved path.

    Raises:
        FileNotFoundError: `must_exist` is True and no candidate exists.
    """
    if name.is_absolute() or name.parent != Path("."):
        candidates = [name]
    elif name.suffix.lower() in CONFIG_SUFFIXES:
        candidates = [folder / name]
    else:
        candidates = [folder / f"{name}{suffix}" for suffix in CONFIG_SUFFIXES]

    for candidate in candidates:
        if candidate.is_file():
            return candidate

    if must_exist:
        tried = ", ".join(str(c) for c in candidates)
        raise FileNotFoundError(f"No config file for {str(name)!r}; tried: {tried}")

    # No match: hand back the first candidate as the canonical target to write to.
    return candidates[0]


class Paths(BaseSettings):
    """Where newswitch keeps configs, schemas, data and logs.

    Every field can be overridden with its own environment variable
    (``NEWSWITCH_CONFIG_DIR``, ``NEWSWITCH_SCHEMA_DIR``, ...). The four are
    independent, so redirecting `config_dir` alone does not move the others.

    Note the ``extra="ignore"``: this class shares the repository's .env with the
    rest of the stack, so an unknown NEWSWITCH_* variable is silently ignored
    rather than reported. A typo like NEWSWITCH_CONFIGG_DIR therefore has no
    effect instead of raising.
    """

    # this is same like model_config = {"env_prefix": "NEWSWITCH_", "env_file": ...}, but with type checking and autocompletion
    # extends BaseSettings to allow for environment variable overrides and .env file loading
    #
    # env_file as an absolute path: a relative ".env" is resolved against the
    # *current working directory*, so a debugger started in the repo root would read
    # a different file than `uv run` started in backend/.
    # extra="ignore": that shared .env also carries BACKEND_PORT & co., and
    # pydantic-settings passes every foreign entry straight through when
    # extra="forbid" (its BaseSettings default), which rejects them as extra inputs.
    model_config = SettingsConfigDict(
        env_prefix="NEWSWITCH_",
        env_file=(_REPO_ROOT / ".env", _REPO_ROOT / "backend" / ".env"),
        extra="ignore",
    )

    # config_dir: Path = _systemd_dir("CONFIGURATION_DIRECTORY") or user_config_path(APP_NAME)
    # data_dir: Path = _systemd_dir("STATE_DIRECTORY") or user_data_path(APP_NAME)
    # log_dir: Path = _systemd_dir("LOGS_DIRECTORY") or user_log_path(APP_NAME)
    config_dir: Path = Path(__file__).parent.parent / "Configs"
    data_dir: Path = Path(__file__).parent.parent / "Configs" / "data"
    log_dir: Path = Path(__file__).parent.parent / "Configs" / "logs"
    schema_dir: Path = Path(__file__).parent.parent / "Configs" / "schemas"

    @property
    def device_settings_file(self) -> Path:
        """Path of the UC2 device settings file inside the config directory."""
        return self.config_dir / "uc2DevSettings.json"

    def config_file(self, name: str | Path, *, must_exist: bool = True) -> Path:
        """Resolve a device/config file name against `config_dir`.

        An explicit path (absolute, or carrying a directory part such as
        ``./cams/hik.yaml``) is returned unchanged, so callers can always bypass the
        managed folder. A bare name is looked up inside `config_dir`:

        * with a known suffix   -> ``config_dir / name``
        * without a suffix      -> the first of .yaml/.yml/.json that exists

        Args:
            name: Bare file name, name without suffix, or an explicit path.
            must_exist: Raise `FileNotFoundError` when nothing was found. Pass False
                when resolving a *target* to write to, which does not exist yet.

        Returns:
            The resolved path.

        Raises:
            FileNotFoundError: `must_exist` is True and no candidate exists.
        """
        return _resolve(Path(name), self.config_dir, must_exist=must_exist)

    def schema_file(self, name: str | Path, *, must_exist: bool = False) -> Path:
        """Resolve a JSON Schema file name against `schema_dir`.

        Same rules as `config_file`, but rooted at `schema_dir` and defaulting to
        `must_exist=False`, because its main use is naming an export target.

        Args:
            name: Bare file name, name without suffix, or an explicit path.
            must_exist: Raise `FileNotFoundError` when nothing was found.

        Returns:
            The resolved path.

        Raises:
            FileNotFoundError: `must_exist` is True and no candidate exists.
        """
        return _resolve(Path(name), self.schema_dir, must_exist=must_exist)

    def ensure_writable_dirs(self) -> None:
        """Ensure that the data and log directories exist and are writable. Not the log directory, which should be created by the deployment."""
        for path in (self.data_dir, self.log_dir, self.schema_dir):
            try:
                path.mkdir(parents=True, exist_ok=True)
            except PermissionError as exc:
                raise RuntimeError(
                    f"Cannot create {path}. Either run under systemd with "
                    f"StateDirectory=/LogsDirectory=, or override via "
                    f"NEWSWITCH_DATA_DIR / NEWSWITCH_LOG_DIR."
                ) from exc
            if not os.access(path, os.W_OK):
                raise RuntimeError(f"{path} exists but is not writable by this user.")


@lru_cache(maxsize=1)
def get_paths() -> Paths:
    """Return the shared `Paths` instance, reading the environment once.

    Returns:
        The cached settings object. Call ``get_paths.cache_clear()`` after changing
        a NEWSWITCH_* variable at runtime, as the tests do.
    """
    return Paths()


"""


 - To be copied to deplay/newswtich.service:
 - than 'sudo systemctl daemon-reload && sudo systemctl enable --now newswitch'

[Unit]
Description=newswitch microscope control backend
After=network-online.target
Wants=network-online.target

[Service]
Type=exec
User=newswitch
Group=newswitch

ConfigurationDirectory=newswitch
StateDirectory=newswitch
LogsDirectory=newswitch

WorkingDirectory=/opt/newswitch
ExecStart=/opt/newswitch/.venv/bin/python -m newswitch.main
Restart=on-failure
RestartSec=5

# Camera/serial access without root:
SupplementaryGroups=video dialout

[Install]
WantedBy=multi-user.target

"""
