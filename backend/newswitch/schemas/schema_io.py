"""Read and write JSON Schema in either JSON or YAML.

Why this works at all
---------------------
JSON Schema is a **data model**, not a file format. The specification defines a
vocabulary over objects, arrays, strings and numbers -- it says nothing about
how those bytes reach you. YAML 1.2 is a superset of JSON and produces exactly
the same Python objects, so a schema written in YAML is the same schema.

The `jsonschema` library takes a **dict**, never a filename:

    Draft202012Validator(yaml.safe_load(open("camera.schema.yaml")))

That is the whole trick. Everything else in this module is convenience and one
genuine gap: cross-file ``$ref``.

The $ref gap
------------
`$ref` to another *file* is the one place the format leaks. The default
retriever fetches the URI and parses it as JSON, so a `$ref` pointing at a
`.yaml` document fails. `build_validator()` installs a `referencing.Registry`
with a YAML-aware retrieve callable to close that.

Internal refs (`#/$defs/Bounded`) are unaffected -- they are JSON Pointers into
the already-parsed dict and never touch the filesystem. Pydantic only ever
emits internal refs, so the exported single-file schemas work without any of
this.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import yaml
from jsonschema import Draft202012Validator
from pydantic import BaseModel
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

DIALECT = "https://json-schema.org/draft/2020-12/schema"
JSON_SUFFIXES = {".json"}
YAML_SUFFIXES = {".yaml", ".yml"}


class SchemaFormatError(ValueError):
    """Raised for unsupported file extensions."""


def load_any(path: str | Path) -> Any:
    """Parse .json, .yaml or .yml into plain Python objects.

    `yaml.safe_load` would in fact read both, since YAML 1.2 is a superset of
    JSON. The split is kept because the JSON parser is stricter and faster, and
    a `.json` file that only parses as YAML is a file worth rejecting.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in JSON_SUFFIXES:
        return json.loads(text)
    if path.suffix.lower() in YAML_SUFFIXES:
        return yaml.safe_load(text)
    raise SchemaFormatError(f"Unsupported file type: {path.suffix}")


def dump_any(obj: Any, path: str | Path) -> Path:
    """Serialize to .json or .yaml, chosen by the file extension."""
    path = Path(path)
    if path.suffix.lower() in JSON_SUFFIXES:
        path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")
    elif path.suffix.lower() in YAML_SUFFIXES:
        path.write_text(
            yaml.safe_dump(obj, sort_keys=False, allow_unicode=True, width=100),
            encoding="utf-8",
        )
    else:
        raise SchemaFormatError(f"Unsupported file type: {path.suffix}")
    return path


def export_schema(
    model: type[BaseModel], path: str | Path, *, header: Optional[str] = None
) -> Path:
    """Write a Pydantic model's JSON Schema to .json or .yaml.

    The model stays the single source of truth; both files are generated
    artifacts. `header` is written as a YAML comment (JSON has no comments, so
    it is dropped there).
    """
    schema = model.model_json_schema()
    schema = {"$schema": DIALECT, **schema}
    path = dump_any(schema, path)

    if header and path.suffix.lower() in YAML_SUFFIXES:
        comment = "\n".join(f"# {line}" for line in header.splitlines())
        path.write_text(
            f"{comment}\n# Generated from {model.__name__} -- do not edit by hand.\n\n"
            + path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    return path


def build_validator(
    schema: dict[str, Any] | str | Path, base_dir: str | Path | None = None
) -> Draft202012Validator:
    """Build a validator whose ``$ref`` resolution understands YAML files.

    Parameters
    ----------
    schema
        A schema dict, or a path to a .json/.yaml schema file.
    base_dir
        Directory that relative ``$ref`` targets are resolved against.
        Defaults to the schema file's own directory.
    """
    if isinstance(schema, (str, Path)):
        base_dir = base_dir or Path(schema).parent
        loaded = load_any(schema)
        if not isinstance(loaded, dict):
            raise SchemaFormatError(
                f"{schema}: expected a mapping at the top level, got {type(loaded).__name__}"
            )
        document: dict[str, Any] = loaded
    else:
        document = schema
    root = Path(base_dir or ".").resolve()

    def retrieve(uri: str) -> Resource:
        """Load a referenced schema file, JSON or YAML alike."""
        target = (root / uri).resolve()
        if not target.is_file():
            raise SchemaFormatError(f"Cannot resolve $ref {uri!r} below {root}")
        return Resource.from_contents(load_any(target), default_specification=DRAFT202012)

    return Draft202012Validator(document, registry=Registry(retrieve=retrieve))


def convert(src: str | Path, dst: str | Path) -> Path:
    """Convert any schema or data file between JSON and YAML."""
    return dump_any(load_any(src), dst)


if __name__ == "__main__":
    import sys

    # Converting between the two formats is what this module uniquely offers.
    # Exporting a model's schema belongs to whoever owns the model: use
    # `device_io.export_json_schema()`, which knows the managed schema directory.
    if len(sys.argv) != 3:
        print(f"usage: python -m {__spec__.name} <src.json|yaml> <dst.json|yaml>")
        raise SystemExit(2)

    print(convert(sys.argv[1], sys.argv[2]))
