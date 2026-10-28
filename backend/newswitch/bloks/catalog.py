"""The newswitch blok module: what the frontend draws beyond the spec's catalogs.

A blok (language v2) is drawn with base, the standard catalogs (``ui@1``, ``scene@1``, ...)
and the Orkestrator's module, which the spec ships, and one module of the app's own.
``newswitch-catalog.json`` is that module: the components the newswitch frontend draws that
none of those hold (the microscope's, the stage's), written by the frontend
(``cd frontend && yarn catalog:export``; its tests fail when the file is stale). The backend
adds nothing to it. The Orkestrator's module is part of every view the spec checks, so a
component only Orkestrator draws (``MikroScene``) passes here although the newswitch
frontend does not draw it.

The catalog is versioned (``NEWSWITCH_CATALOG_VERSION`` in the frontend, bumped on every
change): a configuration's ``ui`` names the one its bloks were written against as
``newswitch@<version>`` (`PublishedCatalog.id`).
"""

import json
from dataclasses import dataclass
from pathlib import Path

from arkitekt import App
from arkitekt_spec.declare.catalogs import Catalog, parse_ui_catalog

from newswitch.config_io import BlokEntry

#: Written by the frontend: ``cd frontend && yarn catalog:export``.
CATALOG_FILE = Path(__file__).parent / "newswitch-catalog.json"
CATALOG_NAME = "newswitch"


@dataclass(frozen=True)
class PublishedCatalog:
    """The catalog the frontend publishes, and its version."""

    catalog: Catalog
    version: int

    @property
    def id(self) -> str:
        """The catalog a configuration names: ``newswitch@<version>``."""
        return f"{CATALOG_NAME}@{self.version}"


def load_catalog(path: Path = CATALOG_FILE) -> PublishedCatalog:
    """Read the catalog the frontend published.

    Raises:
        ValueError: It is not the newswitch catalog, or has no version.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    catalog = parse_ui_catalog(raw)
    if catalog.name != CATALOG_NAME:
        raise ValueError(f"{path.name} is the catalog {catalog.name!r}, not {CATALOG_NAME!r}")
    version = raw.get("version")
    if not isinstance(version, int) or version < 1:
        raise ValueError(f"{path.name} has no version: re-export it (yarn catalog:export)")
    return PublishedCatalog(catalog=catalog, version=version)


def declare_catalog(app: App, published: PublishedCatalog) -> None:
    """Declare the module the frontend publishes on `app`, as it is."""
    app.ui_catalog(
        CATALOG_NAME,
        components=list(published.catalog.components),
        operations=list(published.catalog.operations),
        description=published.catalog.description,
    )


def declare_blok(app: App, name: str, entry: BlokEntry) -> None:
    """Declare a blok drawn with the newswitch module; anything the spec refuses is an error."""
    app.blok(
        name,
        entry.bsx,
        description=entry.description,
        module=CATALOG_NAME,
        default=entry.default,
        mode="strict",
    )
