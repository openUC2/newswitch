"""Structural validation with jsonschema, and export of the schema as YAML.

Why a jsonschema pass before pydantic
-------------------------------------
The devices form a mapping of mixed types, which JSON Schema expresses as ``oneOf``; a
plain validator then reports every branch it tried. Instead each entry's ``type`` is read
first and the entry is checked against the schema of **that** type only, so errors read
``devices.bigcamera42.pixelcount.0: -5 is less than or equal to 0``. All structural
problems of the file are collected in one go. Pydantic runs afterwards for defaults, unit
conversion and cross-field rules. Device entries may carry further keys, so the per-type
schemas allow additional properties; nested values (physical values, connections) do not.

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

from .devices import DEVICE_TYPES, NewswitchConfig
from .document import write_plain

DIALECT = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_FILE_NAME = "newswitch-config.schema.yaml"
TOP_LEVEL_KEYS = ("newswitch_version", "devices")
#: Top-level keys a file may leave out.
OPTIONAL_KEYS = ("assets", "ui", "agent_ui")


def _explain(error: ValidationError) -> tuple[list[str], str]:
    """Descend from an ``anyOf``/``oneOf`` failure to the sub-error that explains it.

    ``pixelcount: [-5, 480]`` then reads "-5 is less than or equal to the minimum of 0"
    instead of "is not valid under any of the given schemas". For a union pydantic tags
    with a ``discriminator`` (connection ``protocol``, transport ``type``) only the branch
    the tag selects is followed, and a missing or unknown tag is reported as such.

    Args:
        error: A top-level validation error.

    Returns:
        ``(path, message)`` of the most relevant leaf error.
    """
    while error.context:
        candidates = error.context
        schema = error.schema if isinstance(error.schema, dict) else {}
        discriminator = schema.get("discriminator")
        if isinstance(discriminator, dict) and isinstance(error.instance, dict):
            name, mapping = discriminator["propertyName"], discriminator["mapping"]
            tag = error.instance.get(name)
            path = [str(p) for p in error.absolute_path]
            if tag is None:
                return path, f"{name!r} is a required property (one of: {', '.join(mapping)})"
            if not isinstance(tag, str) or tag not in mapping:
                return [*path, name], f"{tag!r} is not a known {name} (known: {', '.join(mapping)})"
            branch = [
                i for i, sub in enumerate(schema.get("oneOf", [])) if sub == {"$ref": mapping[tag]}
            ]
            selected = [e for e in error.context if list(e.relative_schema_path)[:1] == branch]
            candidates = selected or candidates
        # deepest path first; among equals, a violated constraint beats a type mismatch
        error = max(
            candidates,
            key=lambda e: (len(e.absolute_path), e.validator != "type", -len(e.context or [])),
        )
    return [str(p) for p in error.absolute_path], error.message


@lru_cache(maxsize=1)
def _type_validators() -> dict[str, Draft202012Validator]:
    """One self-contained validator per device type, built on first use."""
    return {
        name: Draft202012Validator(TypeAdapter(cls).json_schema())
        for name, cls in DEVICE_TYPES.items()
    }


def prepare_document(data: Any) -> tuple[dict[str, Any], list[str]]:  # noqa: ANN401
    """Check the top level; an empty ``devices:`` counts as no devices.

    Args:
        data: The plain parsed document.

    Returns:
        ``(document, problems)``. The document is a new dict; the input is not changed.
    """
    if not isinstance(data, dict):
        return {}, [f"<root>: expected a mapping, got {type(data).__name__}"]

    known = TOP_LEVEL_KEYS + OPTIONAL_KEYS
    problems = [f"<root>: unknown key {key!r}" for key in data if key not in known]
    problems += [f"<root>: missing key {key!r}" for key in TOP_LEVEL_KEYS if key not in data]

    devices = data.get("devices")
    if devices is not None and not isinstance(devices, dict):
        problems.append("devices: expected a mapping of device entries")
    return {**data, "devices": {} if devices is None else devices}, problems


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
        for path, message in sorted(_explain(err) for err in validator.iter_errors(entry)):
            loc = ".".join(path)
            problems.append(f"{where}{'.' + loc if loc else ''}: {message}")
    return problems


def config_schema() -> dict[str, Any]:
    """JSON Schema of the whole configuration file.

    As the file sees it: ``type`` is required (it selects the device class), unlike in the
    Python models, where every class has its own ``type`` as default.

    Returns:
        The schema, with the dialect declared.
    """
    schema = TypeAdapter(NewswitchConfig).json_schema()
    definitions = schema.get("$defs", {})
    for cls in DEVICE_TYPES.values():
        required = definitions[cls.__name__].setdefault("required", [])
        if "type" not in required:
            required.insert(0, "type")
    return {"$schema": DIALECT, **schema}


def export_schema(path: str | Path) -> Path:
    """Write the configuration schema as YAML.

    Args:
        path: Target file, normally `SCHEMA_FILE_NAME` in
            `newswitch.settings.Settings.schema_dir`.

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
