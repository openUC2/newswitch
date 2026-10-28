"""The UI the backend declares: the frontend's module, and the bloks of the configuration."""

import dataclasses
from pathlib import Path

import pytest
from arkitekt import App

from newswitch import config_io
from main_fastapi import create_app
from main_fastapi import create_fastapi_registry
from newswitch.accounts.auth import AllowAllAuthenticator
from newswitch.bloks import CATALOG_NAME, PublishedCatalog, check_catalog, load_catalog
from newswitch.settings import Settings
from newswitch.config_io import UiConfig

CONFIGS = Path(__file__).parent.parent / "configs"
ASSETS = Path(__file__).parent.parent / "newswitch"


def bloks_of(app: App) -> dict[str, list]:
    """Name -> [module, default] of every blok declared on `app`."""
    return {k: [b.module, b.default] for k, b in app.registry.get_declared_bloks().items()}


def configuration(name: str) -> config_io.NewswitchConfig:
    """A shipped device configuration."""
    return config_io.load_config(CONFIGS / name).config


def fluorescence() -> config_io.NewswitchConfig:
    """The fluorescence configuration; skipped where its model is not built."""
    devices = configuration("newswitch-config.fluorescence.yaml")
    if not all((ASSETS / path).is_file() for path in devices.assets.values()):
        pytest.skip("the design's model is not built here: just build-design")
    return devices


def test_the_default_configuration_shows_the_standard_view_first() -> None:
    """Its bloks pass the catalog; the frontend shows `view-standard` first, Minimal beside it."""
    assert bloks_of(create_fastapi_registry(configuration("newswitch-config.yaml"))) == {
        "view-standard": [CATALOG_NAME, True],
        "view-minimal": [CATALOG_NAME, False],
    }


def test_the_camera_configuration_shows_its_camera() -> None:
    """One camera and no stage: a camera view, nothing that needs a stage."""
    assert bloks_of(create_fastapi_registry(configuration("camTest_config.yaml"))) == {
        "view-camera": [CATALOG_NAME, True],
    }


def test_the_fluorescence_configuration_shows_its_microscope() -> None:
    """The configuration built from the fluorescence design: the 3D view first."""
    bloks = bloks_of(create_fastapi_registry(fluorescence()))
    assert bloks["view-3d"] == [CATALOG_NAME, True]
    assert {"view-fluorescence", "view-stage", "view-minimal", "design-camera"} <= set(bloks)


def test_two_apps_in_one_process_share_nothing() -> None:
    """Each registry is created fresh: what one declares never shows up in another."""
    standard = create_fastapi_registry(configuration("newswitch-config.yaml"))
    microscope = create_fastapi_registry(fluorescence())
    bare = create_fastapi_registry(None)

    assert set(bloks_of(standard)) == {"view-standard", "view-minimal"}
    assert "view-3d" in bloks_of(microscope) and "view-standard" not in bloks_of(microscope)
    assert bloks_of(bare) == {}
    assert standard.registry is not microscope.registry


def test_a_configuration_without_ui_does_not_start(tmp_path: Path) -> None:
    """The UI is the configuration's: without a ui section there is nothing to show."""
    config = tmp_path / "newswitch-config.yaml"
    config.write_text("newswitch_version: v1.0.2\ndevices: {}\n")
    settings = Settings(
        static_config_path=config,
        persistent_config_path=tmp_path / "persistent.yaml",
        load_from_static_config_path=True,
    )
    with pytest.raises(config_io.ConfigError, match="no ui section"):
        create_app(settings, AllowAllAuthenticator())


@pytest.mark.parametrize(
    "tree, finding",
    [
        ("<Html><StageView><NoSuchThing /></StageView></Html>", "NoSuchThing"),
        # A scene layer draws into a canvas: it only stands inside a StageScene.
        ("<Html><div><FramesLayer /></div></Html>", "FramesLayer"),
        ('<Html><SettingsPanel colour="red" /></Html>', "colour"),
        # A blok picks a colour role, never a palette colour.
        ('<Html><div className="bg-red-500" /></Html>', "bg-red-500"),
        # Orkestrator's module is part of every view (the spec draws a module over it), so
        # a component only Orkestrator renders (MikroScene) is not refused here.
    ],
)
def test_a_blok_the_frontend_cannot_render_is_refused(tree: str, finding: str) -> None:
    """Strict checking refuses unknown components and props, and misplaced scene layers."""
    app = create_fastapi_registry(None)
    with pytest.raises(ValueError, match=finding):
        app.blok("broken", tree, module=CATALOG_NAME, mode="strict")
    assert "broken" not in app.registry.get_declared_bloks()


def published(version: int) -> PublishedCatalog:
    """The published catalog, at another version."""
    return dataclasses.replace(load_catalog(), version=version)


@pytest.mark.parametrize(
    "written, outcome",
    [("newswitch@1", None), ("newswitch@2", "newer"), ("orkestrator@1", "not the newswitch")],
)
def test_the_ui_names_the_catalog_version_it_is_written_against(
    written: str, outcome: str | None
) -> None:
    """The frontend's version or an older one is checked; a newer or another catalog is refused."""
    ui = UiConfig(catalog=written, bloks={})
    if outcome is None:
        check_catalog(ui, published(1))
    else:
        with pytest.raises(ValueError, match=outcome):
            check_catalog(ui, published(1))


def test_an_older_catalog_version_is_checked_with_a_warning() -> None:
    """Bloks written against an earlier catalog still load, if the current one accepts them."""
    with pytest.warns(UserWarning, match="newswitch@2"):
        check_catalog(UiConfig(catalog="newswitch@2", bloks={}), published(3))


def test_the_published_catalog_is_versioned() -> None:
    """The frontend writes the version into the catalog file; the shipped configurations name it."""
    current = load_catalog().id
    for name in (
        "newswitch-config.yaml",
        "camTest_config.yaml",
        "newswitch-config.fluorescence.yaml",
    ):
        ui = configuration(name).ui
        assert ui is not None and ui.catalog == current


# --- agent mode: the agent_ui bloks, drawn with Orkestrator's module -------------------


@pytest.mark.parametrize(
    "name", ["newswitch-config.yaml", "camTest_config.yaml", "newswitch-config.fluorescence.yaml"]
)
def test_agent_mode_shows_the_agent_ui(name: str) -> None:
    """Every shipped configuration has an agent_ui that passes the spec and Orkestrator's module."""
    pytest.importorskip("lovekit")
    from main_arkitekt import create_arkitekt_registry

    devices = fluorescence() if "fluorescence" in name else configuration(name)
    app = create_arkitekt_registry(devices)
    declared = app.registry.get_declared_bloks()
    # A design-built configuration also has the design's 3D view and the cards it opens.
    designed = {"view-3d", "agent-camera", "agent-laser", "agent-stage"}
    assert set(declared) == {"view-microscope"} | (designed if "fluorescence" in name else set())
    assert all(blok.module is None for blok in declared.values())
    assert declared["view-microscope"].default
    if "fluorescence" in name:
        assert declared["view-3d"].context == "SCENE"
        assert declared["view-3d"].default


def test_agent_mode_refuses_a_newswitch_component() -> None:
    """Orkestrator does not render the newswitch frontend's components."""
    pytest.importorskip("lovekit")
    from main_arkitekt import create_arkitekt_registry

    app = create_arkitekt_registry(None)
    with pytest.raises(ValueError, match="StageControl"):
        app.blok("broken", "<Html><StageControl /></Html>", mode="strict")


def test_the_agent_ui_names_orkestrators_catalog() -> None:
    """An agent_ui written against the newswitch catalog is refused."""
    from newswitch.bloks import check_agent_catalog

    with pytest.raises(ValueError, match="orkestrator"):
        check_agent_catalog(UiConfig(catalog="newswitch@1", bloks={}))
