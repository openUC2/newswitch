"""Load and validate a multi-device file (Devices.yml / Devices.json).

Why not just point jsonschema at the whole file
-----------------------------------------------
A list of mixed types becomes ``oneOf`` in JSON Schema. A plain validator then
reports every branch it tried, so one typo in a camera entry produces four
error blocks ending in "is not valid under any of the given schemas".

`validate_registry()` avoids that by reading the ``type`` field first and
validating each entry against **only** the matching sub-schema. Errors come
back as `devices[2].pixelcount.x: -5 is less than or equal to 0`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from jsonschema import Draft202012Validator
from pydantic import ValidationError

from ..config import get_paths
from .device_schema import DEVICE_MODELS, DeviceRegistry, device_key
from .document import read_document, write_document
from .errors import ConfigError


class DeviceConfigError(ConfigError):
    """Raised when a device file does not satisfy the schema."""


# One self-contained validator per device type.
TYPE_VALIDATORS: dict[str, Draft202012Validator] = {
    name: Draft202012Validator(model.model_json_schema()) for name, model in DEVICE_MODELS.items()
}


def load_raw(path: str | Path) -> Any:  # noqa: ANN401 - a parsed document is Any
    """Parse .json, .yaml or .yml into plain Python objects.

    Args:
        path: Bare config name or an explicit path.

    Returns:
        The parsed document.

    Raises:
        DeviceConfigError: File missing, unsupported suffix, or unparseable.
    """
    try:
        return read_document(path)
    except ConfigError as exc:
        raise DeviceConfigError(str(exc)) from exc


def validate_registry(data: Any) -> list[str]:
    """Return all schema violations as readable strings (empty list = valid).

    Each device is checked against the schema of its own ``type`` only.
    """
    errors: list[str] = []

    if not isinstance(data, dict):
        return ["<root>: expected a mapping with a 'devices' key"]

    if "devices" not in data:
        hint = ""
        if "name" in data or "type" in data:
            hint = (
                " -- this looks like a single-device file; wrap it as "
                "'devices: [ ... ]' or load it with camera_io.load_camera()"
            )
        return [f"<root>: 'devices' is a required property{hint}"]

    unknown = set(data) - set(DeviceRegistry.model_fields)
    for key in sorted(unknown):
        errors.append(f"<root>: unknown key {key!r}")

    devices = data.get("devices")
    if not isinstance(devices, list):
        return errors + ["devices: expected a list of device objects"]

    for i, entry in enumerate(devices):
        where = f"devices[{i}]"

        if not isinstance(entry, dict):
            errors.append(f"{where}: expected an object, got {type(entry).__name__}")
            continue

        type_ = entry.get("type")
        if type_ is None:
            errors.append(f"{where}: missing 'type' discriminator")
            continue
        if type_ not in TYPE_VALIDATORS:
            known = ", ".join(sorted(TYPE_VALIDATORS))
            errors.append(f"{where}: unknown type {type_!r} (known: {known})")
            continue

        for err in sorted(TYPE_VALIDATORS[type_].iter_errors(entry), key=str):
            loc = ".".join(str(p) for p in err.absolute_path)
            errors.append(f"{where}{'.' + loc if loc else ''}: {err.message}")

    return errors


def load_devices(path: str | Path, *, strict_schema: bool = True) -> DeviceRegistry:
    """Load a device file and return a validated registry."""
    data = load_raw(path)

    if strict_schema:
        errors = validate_registry(data)
        if errors:
            joined = "\n  - ".join(errors)
            raise DeviceConfigError(f"{Path(path).name} failed validation:\n  - {joined}")

    try:
        return DeviceRegistry.model_validate(data)
    except ValidationError as exc:
        raise DeviceConfigError(f"{Path(path).name}: {exc}") from exc


def dump_devices(registry: DeviceRegistry, path: str | Path) -> Path:
    """Write a registry back to .json or .yaml.

    Args:
        registry: The validated registry to store.
        path: Bare name (stored in the config dir) or an explicit path.

    Returns:
        The path written to.

    Raises:
        DeviceConfigError: Unsupported file type.
    """
    payload = registry.model_dump(mode="json", by_alias=True, exclude_none=True)
    try:
        return write_document(payload, path)
    except ConfigError as exc:
        raise DeviceConfigError(str(exc)) from exc


def export_json_schema(path: Optional[str | Path] = None) -> Path:
    """Write the registry JSON Schema to disk (editors, docs, other languages).

    Args:
        path: Target file. Defaults to ``devices.schema.json`` in the managed
            schema directory (see `newswitch.config.Paths.schema_dir`).

    Returns:
        The path written to.
    """
    target = get_paths().schema_file("devices.schema.json") if path is None else Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    schema = DeviceRegistry.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    target.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    return target


def describe(registry: DeviceRegistry) -> str:
    """One human-readable line per device."""
    lines = [f"setup: {registry.setup or '-'} (v{registry.version})"]
    for dev in registry.devices:
        detail = ""
        if dev.type == "camera":
            w, h = dev.sensor_size_mm
            detail = f"{dev.pixelcount.x}x{dev.pixelcount.y} px, {w:.1f}x{h:.1f} mm"
        elif dev.type == "stage":
            detail = "axes " + "/".join(a.label for a in dev.axes)
        elif dev.type == "laser":
            detail = f"{dev.wavelength_nm:.0f} nm, {dev.max_power_mw:.0f} mW"
        elif dev.type == "filterwheel":
            detail = f"{len(dev.slots)} slots"
        lines.append(f"  [{dev.type:<11}] {device_key(dev):<22} {detail}")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    for arg in sys.argv[1:] or ["Devices.yml"]:
        try:
            print(describe(load_devices(arg)))
        except DeviceConfigError as exc:
            print(f"[FAIL] {exc}")
