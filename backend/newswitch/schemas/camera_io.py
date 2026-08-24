"""Load and validate camera descriptions from JSON or YAML.

Two validation layers are available:

1. ``jsonschema`` against the exported Draft 2020-12 schema -> reports *all*
   structural errors at once, without constructing a model.
2. ``pydantic`` -> coerces types, applies defaults and runs the derivation
   rules (pixelpitch y -> x, pixelsize -> pixelpitch).

YAML and JSON share the same code path: both parsers produce plain Python
dicts, and validation happens on the dict. Parsing and path resolution live in
`document.py`, so a bare name such as ``"hik_mv_ca023_10um"`` is looked up in the
managed config directory while an explicit path is used as given.

This module is the *camera-only* entry point and rejects anything else. Use
`loader.load_config` when the file may hold a whole device registry.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from jsonschema import Draft202012Validator
from pydantic import ValidationError

from ..config import get_paths
from .camera_schema import CameraSchema
from .document import read_document, write_document
from .errors import ConfigError

CAMERA_VALIDATOR = Draft202012Validator(CameraSchema.model_json_schema())


class CameraConfigError(ConfigError):
    """Raised when a camera description does not satisfy the schema."""


def load_raw(path: str | Path) -> dict[str, Any]:
    """Parse a .json, .yaml or .yml file into a plain dict.

    Args:
        path: Bare config name or an explicit path.

    Returns:
        The parsed document.

    Raises:
        CameraConfigError: File missing/unparseable, or the top level is not a mapping.
    """
    try:
        data = read_document(path)
    except ConfigError as exc:
        raise CameraConfigError(str(exc)) from exc

    if not isinstance(data, dict):
        raise CameraConfigError(f"{Path(path).name}: expected a mapping at the top level")
    return data


def schema_errors(data: dict[str, Any]) -> list[str]:
    """Return all JSON Schema violations as readable strings (empty = valid)."""
    return [
        f"{'.'.join(str(p) for p in err.absolute_path) or '<root>'}: {err.message}"
        for err in sorted(CAMERA_VALIDATOR.iter_errors(data), key=str)
    ]


def load_camera(path: str | Path, *, strict_schema: bool = True) -> CameraSchema:
    """Load a camera description and return a validated model.

    Parameters
    ----------
    path
        Path to a .json, .yaml or .yml file.
    strict_schema
        Run the jsonschema pass first, so that *all* structural problems are
        reported together instead of only the first Pydantic failure.
    """
    data = load_raw(path)

    if strict_schema:
        errors = schema_errors(data)
        if errors:
            joined = "\n  - ".join(errors)
            raise CameraConfigError(f"{Path(path).name} failed validation:\n  - {joined}")

    try:
        return CameraSchema.model_validate(data)
    except ValidationError as exc:
        raise CameraConfigError(f"{Path(path).name}: {exc}") from exc


def dump_camera(camera: CameraSchema, path: str | Path) -> Path:
    """Write a validated camera back to .json or .yaml.

    Args:
        camera: The validated model to store.
        path: Bare name (stored in the config dir) or an explicit path.

    Returns:
        The path written to.

    Raises:
        CameraConfigError: Unsupported file type.
    """
    payload = camera.model_dump(mode="json", by_alias=True, exclude_none=True)
    try:
        return write_document(payload, path)
    except ConfigError as exc:
        raise CameraConfigError(str(exc)) from exc


def export_json_schema(path: Optional[str | Path] = None) -> Path:
    """Write the JSON Schema itself to disk (for editors, docs, other langs).

    Args:
        path: Target file. Defaults to ``camera.schema.json`` in the managed
            schema directory (see `newswitch.config.Paths.schema_dir`).

    Returns:
        The path written to.
    """
    target = get_paths().schema_file("camera.schema.json") if path is None else Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    schema = CameraSchema.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    target.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    return target


if __name__ == "__main__":
    import sys

    for arg in sys.argv[1:] or ["hik_mv_ca023_10um.json", "hik_mv_ca023_10um.yaml"]:
        try:
            cam = load_camera(arg)
        except CameraConfigError as exc:
            print(f"[FAIL] {exc}")
            continue
        w, h = cam.sensor_size_mm
        print(
            f"[ OK ] {arg}: {cam.manufacturer} {cam.name} | "
            f"{cam.pixelcount.x}x{cam.pixelcount.y} px | "
            f"pitch {cam.pixelpitch_um.x}/{cam.pixelpitch_um.y} um | "
            f"sensor {w:.2f}x{h:.2f} mm | fill {cam.fill_factor:.2f}"
        )
