"""Reading and writing config documents, independent of any schema.

This is the one place that knows about file formats and about `config.py`'s folder
layout. Everything above it (`camera_io`, `device_io`, `loader`) works on plain
Python objects and never touches a parser itself.

YAML and JSON share the code path: both parsers produce plain dicts and lists, and
validation happens on those. `yaml.safe_load` would in fact read .json too — YAML 1.2
is a superset — but the suffix is honoured so that a .json file is guaranteed to be
parsed by a strict JSON parser.

Paths are resolved through `newswitch.config.get_paths()`, so a bare name like
``"Devices.yml"`` finds the file in the managed config directory while an explicit
path is used as given. This module sits below `errors.ConfigError` and imports
nothing else from the package, which keeps `loader` importable from `camera_io` and
`device_io` without a cycle.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from ..config import CONFIG_SUFFIXES, get_paths
from .errors import ConfigError


def resolve_source(src: str | Path) -> Path:
    """Resolve a name or path to an existing config file.

    Args:
        src: Bare name (with or without suffix) or an explicit path.

    Returns:
        Path to the existing file.

    Raises:
        ConfigError: Nothing matched; the message lists what was tried.
    """
    try:
        return get_paths().config_file(src)
    except FileNotFoundError as exc:
        raise ConfigError(str(exc)) from exc


def resolve_target(dest: str | Path) -> Path:
    """Resolve a name or path to write to, creating the parent directory.

    Args:
        dest: Bare name or an explicit path. A bare name lands in the config dir.

    Returns:
        Path to write to. It does not have to exist yet.
    """
    path = get_paths().config_file(dest, must_exist=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def read_document(src: str | Path) -> Any:  # noqa: ANN401 - a parsed document is Any
    """Parse a .json, .yaml or .yml config file into plain Python objects.

    Args:
        src: Bare name (with or without suffix) or an explicit path.

    Returns:
        Whatever the file contains — usually a dict, possibly a list.

    Raises:
        ConfigError: Unsupported suffix, missing file, or unparseable content.
    """
    path = resolve_source(src)
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()

    if suffix not in CONFIG_SUFFIXES:
        raise ConfigError(f"Unsupported file type: {path.suffix}")

    try:
        if suffix == ".json":
            return json.loads(text)
        return yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise ConfigError(f"{path.name}: cannot be parsed: {exc}") from exc


def write_document(payload: Any, dest: str | Path) -> Path:  # noqa: ANN401 - JSON-shaped data
    """Serialize `payload` to .json or .yaml, picking the format from the suffix.

    Args:
        payload: JSON-compatible object, e.g. the result of `model_dump(mode="json")`.
        dest: Bare name or an explicit path.

    Returns:
        The path written to.

    Raises:
        ConfigError: Unsupported suffix.
    """
    path = resolve_target(dest)
    suffix = path.suffix.lower()

    if suffix == ".json":
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    elif suffix in {".yaml", ".yml"}:
        path.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
    else:
        raise ConfigError(f"Unsupported file type: {path.suffix}")
    return path
