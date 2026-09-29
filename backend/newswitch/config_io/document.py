"""Reading and writing YAML documents, independent of any schema.

The configuration is read with ruamel.yaml in round-trip mode, so comments, key order
and flow/block style survive a write-back. Validation works on a plain copy
(`to_plain`) of that tree; only the writer touches the tree itself.

Bare names such as ``"newswitch-config.yaml"`` are resolved against the managed config
directory (`newswitch.config.Paths.config_dir`); explicit paths are used as given.
"""

from __future__ import annotations

import io
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from ..config import get_paths
from .errors import ConfigError

#: File name of the one configuration file newswitch reads.
DEFAULT_CONFIG_NAME = "newswitch-config.yaml"


def _represent_none(representer: Any, data: None) -> Any:  # noqa: ANN401 - ruamel API
    """Write None as an explicit ``null`` instead of ruamel's empty value."""
    return representer.represent_scalar("tag:yaml.org,2002:null", "null")


def _round_trip_yaml() -> YAML:
    """Round-trip loader/dumper with the indentation used by the shipped config."""
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 4096  # never re-wrap long lines
    yaml.representer.add_representer(type(None), _represent_none)
    return yaml


def resolve_source(src: str | Path = DEFAULT_CONFIG_NAME) -> Path:
    """Resolve a name or path to an existing YAML file.

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


def read_tree(path: Path) -> Any:  # noqa: ANN401 - a parsed document is Any
    """Parse a YAML file into a ruamel round-trip tree.

    Args:
        path: An existing ``.yaml``/``.yml`` file.

    Returns:
        The tree (usually a ``CommentedMap``).

    Raises:
        ConfigError: Wrong suffix or unparseable content.
    """
    if path.suffix.lower() not in (".yaml", ".yml"):
        raise ConfigError(f"{path.name}: only YAML files are supported")
    try:
        return _round_trip_yaml().load(path.read_text(encoding="utf-8"))
    except YAMLError as exc:
        raise ConfigError(f"{path.name}: cannot be parsed: {exc}") from exc


def to_plain(node: Any) -> Any:  # noqa: ANN401 - mirrors the input
    """Copy a ruamel tree into builtin dicts, lists, str, int, float, bool and None.

    ruamel hands out subclasses (``CommentedMap``, ``ScalarFloat``, ...); jsonschema's
    type checks and pydantic's strict paths want the builtins.

    Args:
        node: Any node of a parsed document.

    Returns:
        The same data built from builtin types only.
    """
    if isinstance(node, dict):
        return {str(k): to_plain(v) for k, v in node.items()}
    if isinstance(node, list):
        return [to_plain(v) for v in node]
    if isinstance(node, bool) or node is None:
        return node
    if isinstance(node, int):
        return int(node)
    if isinstance(node, float):
        return float(node)
    if isinstance(node, str):
        return str(node)
    return node


def dump_tree(tree: Any) -> str:  # noqa: ANN401 - a parsed document is Any
    """Serialize a round-trip tree to text.

    Args:
        tree: The tree returned by `read_tree`, possibly modified.

    Returns:
        The YAML text.
    """
    buffer = io.StringIO()
    _round_trip_yaml().dump(tree, buffer)
    return buffer.getvalue()


def write_tree(tree: Any, path: Path, *, backup: bool = True) -> Path:  # noqa: ANN401
    """Write a round-trip tree atomically, optionally keeping a ``.bak`` of the old file.

    Args:
        tree: The tree to write.
        path: Target file.
        backup: Copy an existing target to ``<name>.bak`` first.

    Returns:
        The path written to.
    """
    text = dump_tree(tree)
    path.parent.mkdir(parents=True, exist_ok=True)
    if backup and path.is_file():
        shutil.copy2(path, path.with_name(path.name + ".bak"))
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return path


def write_plain(data: Any, path: Path, *, header: str | None = None) -> Path:  # noqa: ANN401
    """Write plain data (e.g. a JSON Schema) as block-style YAML.

    Args:
        data: Builtin dicts/lists/scalars.
        path: Target file.
        header: Optional comment written above the document.

    Returns:
        The path written to.
    """
    yaml = YAML(typ="safe", pure=True)
    yaml.default_flow_style = False
    # keep the schema's key order; set on the representer, where the flag is typed as bool
    yaml.representer.sort_base_mapping_type_on_output = False
    yaml.width = 4096
    buffer = io.StringIO()
    yaml.dump(data, buffer)
    text = buffer.getvalue()
    if header:
        text = "".join(f"# {line}\n" for line in header.splitlines()) + "\n" + text
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
