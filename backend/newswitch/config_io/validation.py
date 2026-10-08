"""Structural validation with jsonschema, and export of the schema as YAML.

Why a jsonschema pass before pydantic
-------------------------------------
The devices form a mapping of mixed types, which JSON Schema expresses as ``oneOf``; a
plain validator then reports every branch it tried. Instead each entry's ``type`` is read
first and the entry is checked against the schema of **that** type only, so errors read
``devices.bigcamera42.pixelcount.0: -5 is less than or equal to 0``. All structural
problems of the file are collected in one go. Pydantic runs afterwards for defaults, unit
conversion and cross-field rules.

The schemas are generated from the dataclasses in `devices`, which stay the single
source of truth; the exported ``newswitch-config.schema.yaml`` exists for editors.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from pydantic import TypeAdapter

from .connection import Connection
from .devices import DEVICE_TYPES, NewswitchConfig
from .document import write_plain

DIALECT = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_FILE_NAME = "newswitch-config.schema.yaml"
TOP_LEVEL_KEYS = ("newswitch_version", "connections", "devices")
REQUIRED_TOP_LEVEL_KEYS = ("newswitch_version", "devices")


def _most_specific(error: ValidationError) -> ValidationError:
    """Descend from an ``anyOf``/``oneOf`` failure to the sub-error that explains it.

    ``pixelcount: [-5, 480]`` then reads "-5 is less than or equal to the minimum of 0"
    instead of "is not valid under any of the given schemas".

    Args:
        error: A top-level validation error.

    Returns:
        The most relevant leaf error.
    """
    while error.context:
        # deepest path first; among equals, a violated constraint beats a type mismatch
        error = max(
            error.context,
            key=lambda e: (len(e.absolute_path), e.validator != "type", -len(e.context or [])),
        )
    return error


@lru_cache(maxsize=1)
def _type_validators() -> dict[str, Draft202012Validator]:
    """One self-contained validator per device type, built on first use."""
    return {
        name: Draft202012Validator(TypeAdapter(cls).json_schema())
        for name, cls in DEVICE_TYPES.items()
    }


def prepare_document(data: Any) -> tuple[dict[str, Any], list[str]]:  # noqa: ANN401
    """Check the top level and put each entry's mapping key in as its ``device_id``.

    Args:
        data: The plain parsed document.

    Returns:
        ``(document, problems)``. The document is a new dict; the input is not changed.
        When problems are returned the document may be incomplete.
    """
    if not isinstance(data, dict):
        return {}, [f"<root>: expected a mapping, got {type(data).__name__}"]

    problems = [f"<root>: unknown key {key!r}" for key in data if key not in TOP_LEVEL_KEYS]
    problems += [
        f"<root>: missing key {key!r}" for key in REQUIRED_TOP_LEVEL_KEYS if key not in data
    ]

    devices = data.get("devices")
    if devices is None:
        devices = {}
    if not isinstance(devices, dict):
        return dict(data), problems + ["devices: expected a mapping of device entries"]

    prepared: dict[str, Any] = {}
    for key, entry in devices.items():
        if isinstance(entry, dict):
            stated = entry.get("device_id", key)
            if stated != key:
                problems.append(f"devices.{key}.device_id: {stated!r} differs from key {key!r}")
            entry = {**entry, "device_id": key}
        prepared[key] = entry
    return {**data, "devices": prepared}, problems


def validate_document(document: dict[str, Any]) -> list[str]:
    """Return every structural problem of a prepared document (empty list = valid).

    Args:
        document: Output of `prepare_document`.

    Returns:
        One readable line per problem.
    """
    problems: list[str] = []
    version = document.get("newswitch_version")
    if version is not None and not isinstance(version, str):
        problems.append("newswitch_version: expected a string")

    connections = document.get("connections", {})
    if not isinstance(connections, dict):
        problems.append("connections: expected a mapping of named connections")
    else:
        connection_validator = Draft202012Validator(TypeAdapter(Connection).json_schema())
        for key, entry in connections.items():
            where = f"connections.{key}"
            if not isinstance(entry, dict):
                problems.append(f"{where}: expected a mapping, got {type(entry).__name__}")
                continue
            for err in connection_validator.iter_errors(entry):
                specific = _most_specific(err)
                loc = ".".join(str(p) for p in specific.absolute_path)
                problems.append(f"{where}{'.' + loc if loc else ''}: {specific.message}")

    validators = _type_validators()
    devices = document.get("devices")
    if not isinstance(devices, dict):
        return problems
    for key, entry in devices.items():
        where = f"devices.{key}"
        if not isinstance(entry, dict):
            problems.append(f"{where}: expected a mapping, got {type(entry).__name__}")
            continue
        type_ = entry.get("type")
        if type_ is None:
            problems.append(f"{where}: missing 'type'")
            continue
        validator = validators.get(type_) if isinstance(type_, str) else None
        if validator is None:
            problems.append(
                f"{where}.type: unknown device type {type_!r} (known: {', '.join(DEVICE_TYPES)})"
            )
            continue
        errors = [_most_specific(err) for err in validator.iter_errors(entry)]
        for err in sorted(errors, key=lambda e: [str(p) for p in e.absolute_path]):
            loc = ".".join(str(p) for p in err.absolute_path)
            problems.append(f"{where}{'.' + loc if loc else ''}: {err.message}")
    return problems


def config_schema() -> dict[str, Any]:
    """JSON Schema of the whole configuration file.

    As the file sees it: ``device_id`` is optional (the mapping key supplies it) and
    ``type`` is required (it selects the device class), unlike in the Python models.

    Returns:
        The schema, with the dialect declared.
    """
    schema = TypeAdapter(NewswitchConfig).json_schema()
    for definition in schema.get("$defs", {}).values():
        properties = definition.get("properties", {})
        required = definition.get("required", [])
        if "device_id" in required:
            required.remove("device_id")
        if "type" in properties and "device_id" in properties and "type" not in required:
            required.insert(0, "type")
    return {"$schema": DIALECT, **schema}


def export_schema(path: str | Path) -> Path:
    """Write the configuration schema as YAML.

    Args:
        path: Target file, normally `SCHEMA_FILE_NAME` in
            `newswitch.app.ImswitchConfig.schema_dir`.

    Returns:
        The path written to.
    """
    return write_plain(
        config_schema(),
        Path(path),
        header=(
            "JSON Schema (Draft 2020-12) for newswitch-config.yaml.\n"
            "Generated from newswitch.config_io.devices -- do not edit by hand.\n"
            "Regenerate with: uv run python -m newswitch.config_io --export-schema"
        ),
    )
