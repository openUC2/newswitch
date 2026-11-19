"""The UI the backend serves: the frontend's catalog, and the bloks of the instrument.

`declare_ui` declares two things on an app registry and composes nothing:

1. the catalog, exactly as the frontend publishes it (`catalog.CATALOG_FILE`);
2. the bloks of the description's ``ui`` section (their BSX source). Each is one
   ``<Blok kind="agent" context="panel" catalog="newswitch">`` and is checked against the catalog;
   one it refuses stops the backend. ``ui.catalog`` names the catalog version they were written
   against (``newswitch@<version>``): a newer one than the frontend's is refused, an older one is
   checked all the same, with a warning.

The views the frontend's bottom bar switches between are the bloks keyed ``view-…`` (their
description starts with the tab's label); the one marked ``default`` is shown first.

`declare_agent_ui` declares the description's ``agent_ui`` section instead, for Orkestrator: bloks
written for the base catalog or Orkestrator's (``<Blok catalog="https://arkitekt.live/...">``).
A description without the section shows nothing there: no blok comes from anywhere else.

A registry holds a blok to the blok language alone; the catalog rules run only inside
`checking_catalogs`. Both declare their bloks inside it with every catalog finding an error, so a
blok the catalog refuses stops the start. The one finding let through is ``class.not_portable``
for the frontend's bloks: it is about renderers without CSS, and the frontend draws all of
Tailwind.
"""

import re
import warnings
from collections.abc import Iterable

from arkitekt import ORKESTRATOR_CATALOG_ID, App, checking_catalogs
from arkitekt_spec.declare.app import source_catalog
from arkitekt_spec.declare.catalogs import CatalogWarning

from newswitch.infra.ui.catalog import (
    CATALOG_FILE,
    CATALOG_NAME,
    PublishedCatalog,
    declare_catalog,
    load_catalog,
)
from newswitch.instrument.spec import Instrument
from newswitch.instrument.ui import BlokEntry, UiConfig

#: What an ``agent_ui`` blok may be written for: the base catalog (None) or Orkestrator's.
AGENT_CATALOGS: frozenset[str | None] = frozenset({None, ORKESTRATOR_CATALOG_ID})

#: Findings a ``ui`` blok may carry: the frontend compiles Tailwind, so every class draws.
UI_TOLERATED: frozenset[str] = frozenset({"class.not_portable"})

__all__ = [
    "AGENT_CATALOGS",
    "CATALOG_FILE",
    "CATALOG_NAME",
    "PublishedCatalog",
    "UI_TOLERATED",
    "check_catalog",
    "declare_agent_ui",
    "declare_bloks",
    "declare_ui",
    "load_catalog",
]


def check_catalog(ui: UiConfig, published: PublishedCatalog) -> None:
    """Check `ui` is written against `published`, at its version or before.

    Raises:
        ValueError: It names another catalog, or a newer version than the published one.
    """
    name, _, version = ui.catalog.partition("@")
    if name != CATALOG_NAME:
        raise ValueError(
            f"the ui is written against {ui.catalog!r}, not the {CATALOG_NAME} catalog"
        )
    if not version.isdigit():
        raise ValueError(f"the ui names {ui.catalog!r}: a {CATALOG_NAME} version is a number")
    if int(version) > published.version:
        raise ValueError(
            f"the ui is written against {ui.catalog}, newer than the frontend's {published.id}"
        )
    if int(version) < published.version:
        warnings.warn(
            f"the ui is written against {ui.catalog}, the frontend publishes {published.id}: "
            f"its bloks are checked against {published.id}; once they pass, set ui.catalog",
            stacklevel=2,
        )


def _catalog_label(catalog: str | None) -> str:
    return repr(catalog) if catalog else "the base catalog"


def declare_bloks(
    app: App,
    section: str,
    bloks: dict[str, BlokEntry],
    allowed: Iterable[str | None],
    tolerated: Iterable[str] = (),
) -> None:
    """Declare `bloks` on `app`, each written for one of `allowed` and held to it.

    Every catalog finding refuses the blok, but those whose code is in `tolerated`.

    Raises:
        ValueError: A blok is written for another catalog, or its catalog refuses it.
    """
    allowed = frozenset(allowed)
    for name, entry in bloks.items():
        catalog = source_catalog(entry.bsx)
        if catalog not in allowed:
            wanted = " or ".join(sorted(_catalog_label(c) for c in allowed))
            raise ValueError(
                f"{section}.bloks.{name} is written for {_catalog_label(catalog)}, not {wanted}"
            )
        with checking_catalogs(), warnings.catch_warnings():
            warnings.simplefilter("error", CatalogWarning)
            for code in tolerated:
                warnings.filterwarnings(
                    "ignore", message=rf".*\[{re.escape(code)}\]$", category=CatalogWarning
                )
            try:
                app.blok(name, entry.bsx, description=entry.description, default=entry.default)
            except CatalogWarning as finding:
                raise ValueError(f"{section}.bloks.{name}: {finding}") from None


def declare_ui(
    app: App,
    instrument: Instrument | None,
    published: PublishedCatalog | None = None,
) -> None:
    """Declare the newswitch frontend's catalog and the ``ui`` bloks of `instrument` (FastAPI mode).

    Raises:
        ValueError: The catalog refuses a blok, or is not the one the ui names.
    """
    published = published or load_catalog()
    declare_catalog(app, published)
    if instrument is None or instrument.ui is None:
        return
    check_catalog(instrument.ui, published)
    declare_bloks(app, "ui", instrument.ui.bloks, {CATALOG_NAME}, UI_TOLERATED)


def declare_agent_ui(app: App, instrument: Instrument | None) -> None:
    """Declare the ``agent_ui`` bloks of `instrument`, for Orkestrator (agent mode).

    Orkestrator renders them, so they are checked strictly against the catalog each names (the
    base catalog or Orkestrator's; never newswitch's) and against what `app` registered.

    Raises:
        ValueError: The catalog refuses a blok, or a blok is written for another catalog.
    """
    if instrument is None or instrument.agent_ui is None:
        return
    declare_bloks(app, "agent_ui", instrument.agent_ui.bloks, AGENT_CATALOGS)
