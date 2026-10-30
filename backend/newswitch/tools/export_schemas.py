"""Export the schemas the frontend generates its typed hooks from.

    uv run python -m newswitch.tools.export_schemas            # writes ../frontend/schemas/*.json

What newswitch registers depends on the instrument (`newswitch.microscope.registry`),
but the frontend's hooks must cover everything newswitch can do. So they are generated
from the schemas of a complete microscope (`REFERENCE_INSTRUMENT`: every part), written here into
committed files the frontend's codegen reads (``frontend/plugins/generate-app.ts``),
whatever instrument a running backend has. The mirror of the blok catalog, which the
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

from newswitch.instrument import spec

#: A microscope with every part (and no UI): what the frontend's hooks are generated from.
REFERENCE_INSTRUMENT = Path(__file__).parents[1] / "reference" / "complete-microscope"
#: Read by the frontend's codegen.
SCHEMA_DIR = Path(__file__).parents[3] / "frontend" / "schemas"
#: The states of every part: a microscope without one has no hooks for it.
EVERY_PART = {
    "StageState",
    "IlluminationState",
    "CameraState",
    "ObjectiveState",
    "FilterBankState",
    "UC2State",
}


def served_schemas(instrument: Path = REFERENCE_INSTRUMENT) -> dict[str, Any]:
    """File name -> what a FastAPI backend on `instrument` serves for it.

    Raises:
        ValueError: `instrument` lacks a part: its hooks would be missing in the frontend.
    """
    # What the served agent takes when it starts (arkitekt_fastapi's lifespan), and what its
    # /schemas/* routes return from it.
    registry = create_fastapi_registry(spec.load(instrument)).registry.snapshot()
    missing = sorted(EVERY_PART - set(registry.states))
    if missing:
        raise ValueError(f"{instrument.name} is not a complete microscope: it lacks {missing}")

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


def export(out: Path = SCHEMA_DIR, instrument: Path = REFERENCE_INSTRUMENT) -> list[Path]:
    """Write the schemas of `instrument` into `out`."""
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, schema in served_schemas(instrument).items():
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
