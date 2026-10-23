"""Export the schemas the frontend generates its typed hooks from.

    uv run python -m newswitch.tools.export_schemas            # writes ../frontend/schemas/*.json

What newswitch registers depends on the device configuration (`newswitch.microscope.registry`),
but the frontend's hooks must cover everything newswitch can do. So they are generated
from the schemas of a complete microscope (`REFERENCE_CONFIG`: every part), written here into
committed files the frontend's codegen reads (``frontend/plugins/generate-app.ts``),
whatever configuration a running backend has. The mirror of the blok catalog, which the
frontend exports for the backend.

The frontend talks to newswitch served by FastAPI (``main_fastapi.py``), so the
files are exactly what a FastAPI backend on the reference microscope serves at
``/schemas/implementations``, ``/schemas/states`` and ``/schemas/locks``: the same objects,
from a snapshot of its app registry (what the served agent takes when it starts), encoded
the same way. Nothing is started. Re-export after changing an action, state or lock;
``just drift-check`` fails on a stale export.
"""

import argparse
import json
from pathlib import Path
from typing import Any

from fastapi.encoders import jsonable_encoder

from main_fastapi import create_fastapi_registry

from newswitch import config_io
from newswitch.settings import BASE_CONFIG_FILE
from newswitch.microscope.parts import configured_parts

#: A microscope with every part (and no UI): what the frontend's hooks are generated from.
REFERENCE_CONFIG = Path(__file__).parents[1] / "reference" / "complete-microscope.yaml"
#: Read by the frontend's codegen.
SCHEMA_DIR = BASE_CONFIG_FILE.parent.parent / "frontend" / "schemas"
PARTS = ["stage", "illumination", "detector", "objective", "filter bank", "uc2"]


def served_schemas(config: Path = REFERENCE_CONFIG) -> dict[str, Any]:
    """File name -> what a FastAPI backend on the microscope of `config` serves for it.

    Raises:
        ValueError: `config` lacks a part: its hooks would be missing in the frontend.
    """
    devices = config_io.load_config(config).config
    parts = configured_parts(devices).names()
    missing = [part for part in PARTS if part not in parts]
    if missing:
        raise ValueError(f"{config.name} is not a complete microscope: it lacks {missing}")

    # What the served agent takes when it starts (arkitekt_fastapi's lifespan), and what its
    # /schemas/* routes return from it.
    registry = create_fastapi_registry(devices).registry.snapshot()
    implementations = {
        impl.interface or impl.definition.name: impl for impl in registry.get_implementations()
    }
    states = dict(registry.states)
    locks = {lock.key: lock for lock in registry.get_locks()}
    return jsonable_encoder(
        {
            "implementations.json": {
                "count": len(implementations),
                "implementations": implementations,
            },
            "states.json": {"count": len(states), "states": states},
            "locks.json": {"count": len(locks), "locks": locks},
        }
    )


def export(out: Path = SCHEMA_DIR, config: Path = REFERENCE_CONFIG) -> list[Path]:
    """Write the schemas of the microscope of `config` into `out`."""
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, schema in served_schemas(config).items():
        target = out / name
        target.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
        written.append(target)
    return written


def main(argv: list[str] | None = None) -> None:
    """Command line: ``python -m newswitch.tools.export_schemas [-o DIR]``."""
    parser = argparse.ArgumentParser(description="Export the schemas the frontend generates from.")
    parser.add_argument("-o", "--out", type=Path, default=SCHEMA_DIR, help="folder to write into")
    args = parser.parse_args(argv)
    for path in export(args.out):
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
