"""The newswitch blok catalog: the standard components and operations, plus the microscope's.

The microscope's components (control panels, the stage view and its scene layers) are
published in ``newswitch-catalog.json``, which the frontend writes (``yarn catalog:export``;
its tests fail when the file is stale), so a blok declared with ``catalog="newswitch"`` is
checked against exactly what the frontend renders.
"""

import json
from pathlib import Path

from arkitekt_spec.declare.catalogs import load_standard_catalog, parse_ui_catalog

from newswitch.arkitekt_app import nsapp

#: Written by the frontend: ``cd frontend && yarn catalog:export``.
CATALOG_FILE = Path(__file__).parent / "newswitch-catalog.json"
CATALOG_NAME = "newswitch"


def declare_catalog() -> None:
    """Declare the newswitch catalog: the standard components and operations, plus ours."""
    base = load_standard_catalog()
    microscope = parse_ui_catalog(json.loads(CATALOG_FILE.read_text(encoding="utf-8")))
    nsapp.ui_catalog(
        CATALOG_NAME,
        components=[*base.components, *microscope.components],
        operations=list(base.operations),
        description=microscope.description,
    )
