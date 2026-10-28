"""The UI the backend serves: the frontend's catalog, and the bloks of the device configuration.

`declare_ui` declares two things on an app registry and composes nothing:

1. the catalog, exactly as the frontend publishes it (`catalog.CATALOG_FILE`);
2. the bloks of the device configuration's ``ui`` section (their BSX source), with the files
   they read from its ``assets``. Each is checked against the catalog; one it refuses stops
   the backend. ``ui.catalog`` names the catalog version they were written against
   (``newswitch@<version>``): a newer one than the frontend's is refused, an older one is
   checked all the same, with a warning.

The views the frontend's bottom bar switches between are the bloks keyed ``view-…`` (their
description starts with the tab's label); the one marked ``default`` is shown first.

The modules beside this one (`design`, `fluorescence`, `minimal`, `stage_view`) are not
used when newswitch runs: they write the ``ui`` of a configuration built from an optikit
design (``python -m newswitch.tools.build_design``).
"""

import warnings
from pathlib import Path

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
from newswitch.config_io import NewswitchConfig, UiConfig

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

#: Where assets are found: the app's root (``newswitch/``).
ASSET_ROOT = Path(__file__).parent.parent


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


def _register_assets(app: App, devices: NewswitchConfig) -> None:
    for name, path in devices.assets.items():
        if not (ASSET_ROOT / path).is_file():
            raise FileNotFoundError(
                f"the asset {name!r} ({ASSET_ROOT / path}) is missing: rebuild the "
                "configuration with python -m newswitch.tools.build_design"
            )
        app.register_asset(name, path)


def declare_ui(
    app: App, devices: NewswitchConfig | None, published: PublishedCatalog | None = None
) -> None:
    """Declare the newswitch frontend's catalog and the ``ui`` bloks of `devices` (FastAPI mode).

    Raises:
        FileNotFoundError: An asset of the configuration is missing.
        ValueError: The catalog refuses a blok, or is not the one the ui names.
    """
    published = published or load_catalog()
    declare_catalog(app, published)
    if devices is None or devices.ui is None:
        return
    check_catalog(devices.ui, published)
    _register_assets(app, devices)
    for name, entry in devices.ui.bloks.items():
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


def declare_agent_ui(app: App, devices: NewswitchConfig | None) -> None:
    """Declare the ``agent_ui`` bloks of `devices`, in Orkestrator's catalog (agent mode).

    Orkestrator renders them, so they are checked strictly against the spec's catalogs and
    Orkestrator's module (no module of newswitch's own) and against what `app` registered.

    Raises:
        FileNotFoundError: An asset of the configuration is missing.
        ValueError: The catalog refuses a blok, or the agent_ui names another catalog.
    """
    if devices is None or devices.agent_ui is None:
        return
    check_agent_catalog(devices.agent_ui)
    _register_assets(app, devices)
    for name, entry in devices.agent_ui.bloks.items():
        app.blok(
            name,
            entry.bsx,
            description=entry.description,
            default=entry.default,
            mode="strict",
        )
