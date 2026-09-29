"""Guards against drift between the dataclasses and the files shipped next to them.

1. ``Configs/schemas/newswitch-config.schema.yaml`` must match the dataclasses.
2. ``Configs/newswitch-config.yaml`` must load and pass the exported schema.

Both read the development-only ``Configs/`` folder and skip when it is gone.
Regenerate the schema with ``uv run python -m newswitch.config_io --export-schema``.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from ruamel.yaml import YAML

from newswitch.config import Paths
from newswitch.config_io import config_schema, load_config
from newswitch.config_io.document import to_plain
from newswitch.config_io.validation import SCHEMA_FILE_NAME

CONFIG_FILE = Paths().config_dir / "newswitch-config.yaml"
SCHEMA_FILE = Paths().schema_dir / SCHEMA_FILE_NAME


def _requires(path: Path) -> Path:
    if not path.is_file():
        pytest.skip(f"{path} is not present")
    return path


def _load(path: Path) -> object:
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
