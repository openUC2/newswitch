"""The UI the backend declares: the frontend's module, and the views of the instrument."""

import dataclasses
from pathlib import Path

import pytest
from arkitekt import App

from main_fastapi import create_fastapi_registry
from newswitch.bloks import CATALOG_NAME, PublishedCatalog, check_catalog, load_catalog
from newswitch.instrument import spec
from newswitch.instrument.ui import UiConfig
from newswitch.tools.export_schemas import REFERENCE_INSTRUMENT

INSTRUMENTS = Path(__file__).parent.parent / "instruments"
FAKE = INSTRUMENTS / "fake-microscope"
CAM_TEST = INSTRUMENTS / "cam-test"


def bloks_of(app: App) -> dict[str, list]:
    """Name -> [module, default] of every blok declared on `app`."""
    return {k: [b.module, b.default] for k, b in app.registry.get_declared_bloks().items()}


def test_the_bloks_are_the_ones_its_description_holds() -> None:
    """They pass the catalog; the frontend shows the one marked default first."""
    assert bloks_of(create_fastapi_registry(spec.load(FAKE))) == {
        "view-bench": [CATALOG_NAME, True],
        "view-fluorescence": [CATALOG_NAME, False],
        "view-stage": [CATALOG_NAME, False],
        "view-minimal": [CATALOG_NAME, False],
    }


def test_a_camera_alone_shows_its_camera() -> None:
    """One camera and no stage: a view of it, nothing that needs a stage."""
    assert bloks_of(create_fastapi_registry(spec.load(CAM_TEST))) == {
        "view-camera": [CATALOG_NAME, True],
    }


def test_two_apps_in_one_process_share_nothing() -> None:
    """Each registry is created fresh: what one declares never shows up in another."""
    fake = create_fastapi_registry(spec.load(FAKE))
    camera = create_fastapi_registry(spec.load(CAM_TEST))
    bare = create_fastapi_registry(None)

    assert "view-stage" in bloks_of(fake) and "view-stage" not in bloks_of(camera)
    assert bloks_of(bare) == {}
    assert fake.registry is not camera.registry


def test_a_description_without_bloks_has_none() -> None:
    """No blok comes from anywhere else; the reference microscope is there for its actions."""
    assert bloks_of(create_fastapi_registry(spec.load(REFERENCE_INSTRUMENT))) == {}


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


def test_the_shipped_bloks_name_the_published_catalog() -> None:
    """The frontend writes the version into the catalog file; the descriptions name it."""
    current = load_catalog().id
    for instrument in (FAKE, CAM_TEST):
        ui = spec.load(instrument).ui
        assert ui is not None and ui.catalog == current


# --- agent mode: the agent_ui bloks, drawn with Orkestrator's module -------------------


@pytest.mark.parametrize("instrument", [FAKE, CAM_TEST])
def test_agent_mode_shows_the_agent_ui(instrument: Path) -> None:
    """Every shipped instrument has an agent_ui that passes the spec and Orkestrator's module."""
    pytest.importorskip("lovekit")
    from main_arkitekt import create_arkitekt_registry

    declared = create_arkitekt_registry(spec.load(instrument)).registry.get_declared_bloks()
    assert set(declared) == {"view-microscope"}
    assert declared["view-microscope"].module is None
    assert declared["view-microscope"].default


def test_agent_mode_without_an_agent_ui_shows_nothing() -> None:
    """No blok comes from anywhere else."""
    pytest.importorskip("lovekit")
    from main_arkitekt import create_arkitekt_registry

    app = create_arkitekt_registry(spec.load(REFERENCE_INSTRUMENT))
    assert app.registry.get_declared_bloks() == {}


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
