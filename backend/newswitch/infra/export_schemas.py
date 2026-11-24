"""Export the schemas the frontend generates its typed hooks from.

    uv run python -m newswitch.infra.export_schemas            # writes ../frontend/schemas/*.json

What newswitch registers is the same on every microscope (`newswitch.microscope.registry`), so
the frontend's hooks cover everything newswitch can do whatever instrument a running backend has.
They are generated from the schemas of that registry, written here into committed files the
frontend's codegen reads (``frontend/plugins/generate-app.ts``). The mirror of the blok catalog,
which the frontend exports for the backend.

The frontend talks to newswitch served by FastAPI (``main_fastapi.py``), so the
files are exactly what a FastAPI backend serves at
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
from newswitch.logging_setup import console, setup_logging

#: Read by the frontend's codegen.
SCHEMA_DIR = Path(__file__).parents[3] / "frontend" / "schemas"

#: What this tool reports: to stdout, and into the log file.
report = console("export_schemas")


def served_schemas() -> dict[str, Any]:
    """File name -> what a FastAPI backend serves for it, on any microscope."""
    # What the served agent takes when it starts (arkitekt_fastapi's lifespan), and what its
    # /schemas/* routes return from it. The ``ui`` bloks are not in them: no instrument is needed.
    registry = create_fastapi_registry(None).registry.snapshot()

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


def export(out: Path = SCHEMA_DIR) -> list[Path]:
    """Write the schemas into `out`."""
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, schema in served_schemas().items():
        target = out / name
        target.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
        written.append(target)
    return written


def main(argv: list[str] | None = None) -> None:
    """Command line: ``python -m newswitch.infra.export_schemas [-o DIR]``."""
    setup_logging()
    parser = argparse.ArgumentParser(description="Export the schemas the frontend generates from.")
    parser.add_argument("-o", "--out", type=Path, default=SCHEMA_DIR, help="folder to write into")
    args = parser.parse_args(argv)
    for path in export(args.out):
        report.info("wrote %s", path)


if __name__ == "__main__":
    main()
