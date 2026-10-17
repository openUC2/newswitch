"""Guards against drift between the dataclasses and the files shipped next to them.

1. ``Configs/schemas/newswitch-config.schema.yaml`` must match the dataclasses.
2. ``Configs/newswitch-config.yaml`` must load and pass the exported schema.

Both read the development-only ``Configs/`` folder (located via ``base_config.yaml``)
and skip when it is gone.
Regenerate the schema with ``uv run python -m newswitch.config_io --export-schema``.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from ruamel.yaml import YAML

from newswitch.app import ImswitchConfig
from newswitch.config_io import config_schema, load_config
from newswitch.config_io.document import to_plain
from newswitch.config_io.validation import SCHEMA_FILE_NAME

_SETTINGS = ImswitchConfig(config_file=None)
CONFIG_FILE = _SETTINGS.static_config_path
SCHEMA_FILE = _SETTINGS.schema_dir / SCHEMA_FILE_NAME


def _requires(path: Path) -> Path:
    if not path.is_file():
        pytest.skip(f"{path} is not present")
    return path


def _load(path: Path) -> Any:  # noqa: ANN401 - a parsed document is Any
    return to_plain(YAML(typ="safe").load(path))


def test_exported_schema_is_current() -> None:
    """The committed schema equals a fresh export."""
    assert _load(_requires(SCHEMA_FILE)) == config_schema()


def test_example_config_loads_cleanly() -> None:
    """The shipped config loads without warnings and passes the exported schema."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        load_config(_requires(CONFIG_FILE))
    validator = Draft202012Validator(_load(_requires(SCHEMA_FILE)))
    assert [e.message for e in validator.iter_errors(_load(CONFIG_FILE))] == []
