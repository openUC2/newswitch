"""The UI the backend serves: the frontend's catalog, and the bloks of the instrument.

`declare_ui` declares two things on an app registry and composes nothing:

1. the catalog, exactly as the frontend publishes it (`catalog.CATALOG_FILE`);
2. the bloks of the description's ``ui`` section (their BSX source). Each is checked against the
   catalog; one it refuses stops the backend. ``ui.catalog`` names the catalog version they were
   written against (``newswitch@<version>``): a newer one than the frontend's is refused, an older
   one is checked all the same, with a warning.

The views the frontend's bottom bar switches between are the bloks keyed ``view-…`` (their
description starts with the tab's label); the one marked ``default`` is shown first.

`declare_agent_ui` declares the description's ``agent_ui`` section instead, for Orkestrator. A
description without the section shows nothing there: no blok comes from anywhere else.
"""

import warnings

from arkitekt import App
from arkitekt_spec.declare.catalogs import STANDARD_CATALOG_NAME, standard_catalog_release

from newswitch.bloks.catalog import (
    CATALOG_FILE,
    CATALOG_NAME,
    PublishedCatalog,
    declare_blok,
    declare_catalog,
    load_catalog,
)
from newswitch.instrument.spec import Instrument
from newswitch.instrument.ui import UiConfig

__all__ = [
    "CATALOG_FILE",
    "CATALOG_NAME",
    "PublishedCatalog",
    "check_agent_catalog",
    "check_catalog",
    "declare_agent_ui",
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
    for name, entry in instrument.ui.bloks.items():
        declare_blok(app, name, entry)


def check_agent_catalog(ui: UiConfig) -> None:
    """Check `ui` is written against Orkestrator's standard catalog.

    The standard catalog is the one arkitekt ships (an Orkestrator release); bloks written
    against another release are checked against the shipped one all the same, with a warning.

    Raises:
        ValueError: It names another catalog.
    """
    name, _, release = ui.catalog.partition("@")
    if name != STANDARD_CATALOG_NAME:
        raise ValueError(
            f"the agent_ui is written against {ui.catalog!r}, not Orkestrator's "
            f"{STANDARD_CATALOG_NAME} catalog"
        )
    shipped = standard_catalog_release()
    if release != shipped:
        warnings.warn(
            f"the agent_ui is written against {ui.catalog}, arkitekt ships "
            f"{STANDARD_CATALOG_NAME}@{shipped}: its bloks are checked against that",
            stacklevel=2,
        )


def declare_agent_ui(app: App, instrument: Instrument | None) -> None:
    """Declare the ``agent_ui`` bloks of `instrument`, in Orkestrator's catalog (agent mode).

    Orkestrator renders them, so they are checked strictly against the spec's catalogs and
    Orkestrator's module (no module of newswitch's own) and against what `app` registered.

    Raises:
        ValueError: The catalog refuses a blok, or the agent_ui names another catalog.
    """
    if instrument is None or instrument.agent_ui is None:
        return
    check_agent_catalog(instrument.agent_ui)
    for name, entry in instrument.agent_ui.bloks.items():
        app.blok(
            name,
            entry.bsx,
            description=entry.description,
            default=entry.default,
            mode="strict",
        )
