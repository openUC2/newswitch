"""The global settings of the backend, whatever the microscope: ``backend/sys_config.yaml``.

What belongs to one microscope is in its description (`newswitch.settings`, the ``settings``
section of its ``microscope.yml``). What does not depend on the microscope is here: how the
backend logs (`newswitch.logging_setup`) and whether the cameras show a debug window
(`newswitch.microscope.parts.build_detector_manager`). Every key must be there, and an unknown
one is an error, so a misspelled key is not quietly ignored.

`load_sys_config` reads it; the entry points do so through `newswitch.logging_setup.setup_logging`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, StrictBool, ValidationError, field_validator

from newswitch.logging_setup import LogLevel
from newswitch.settings import BACKEND_DIR

#: The file; read at the time `load_sys_config` is called, so tests can point it elsewhere.
SYS_CONFIG_FILE = BACKEND_DIR / "sys_config.yaml"


class SysConfigError(ValueError):
    """``sys_config.yaml`` is missing, or is not what it must be."""


class SysConfig(BaseModel):
    """``sys_config.yaml``: every key must be there, and none other."""

    model_config = ConfigDict(extra="forbid")

    log_to_terminal: LogLevel
    """Lowest level of the log records written to the terminal (stderr)."""
    log_to_file: LogLevel
    """Lowest level of the log records written to `log_file_path`."""
    log_file_path: Path | None
    """The log file, relative to ``backend/``. null or empty: ``backend/backend.log``, with a
    warning in it."""
    camera_debug_window: StrictBool
    """Show every real camera's newest image in a window of uc2_cam_py (debugging without the
    frontend); the cameras then acquire from startup on. Simulated cameras show none."""

    @field_validator("log_file_path", mode="before")
    @classmethod
    def _blank_is_none(cls, value: Any) -> Any:  # noqa: ANN401 - raw input of any shape
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("log_file_path")
    @classmethod
    def _relative_to_backend(cls, path: Path | None) -> Path | None:
        if path is None or path.is_absolute():
            return path
        return BACKEND_DIR / path


def load_sys_config(path: Path | None = None) -> SysConfig:
    """Read `path` (default: `SYS_CONFIG_FILE`).

    Raises:
        SysConfigError: The file is missing or unreadable, or a key is missing, unknown or of
            the wrong value; the message names the file and every such key.
    """
    path = SYS_CONFIG_FILE if path is None else path
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SysConfigError(f"{path} cannot be read ({exc}); the backend needs it") from exc
    except yaml.YAMLError as exc:
        raise SysConfigError(f"{path} is no valid YAML: {exc}") from exc
    try:
        return SysConfig.model_validate(data if data is not None else {})
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or '(top level)'}: {error['msg']}"
            for error in exc.errors()
        )
        raise SysConfigError(f"{path}: {problems}") from exc
