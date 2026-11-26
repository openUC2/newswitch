"""The UI the backend declares: the frontend's module and the instrument's views, and the agent's own."""

import dataclasses
from pathlib import Path

import pytest
from arkitekt import ORKESTRATOR_CATALOG_ID, App

from main_fastapi import create_fastapi_registry
from newswitch.infra.ui import (
    AGENT_BLOKS,
    AGENT_CATALOGS,
    CATALOG_NAME,
    UI_TOLERATED,
    PublishedCatalog,
    agent_bloks,
    check_catalog,
    declare_bloks,
    load_catalog,
)
from newswitch.instrument import spec
from newswitch.instrument.ui import BlokEntry, UiConfig
from newswitch.reference import REFERENCE_INSTRUMENT

INSTRUMENTS = Path(__file__).parent.parent / "instruments"
FAKE = INSTRUMENTS / "fake-microscope"
CAM_TEST = INSTRUMENTS / "cam-test"


def bloks_of(app: App) -> dict[str, list]:
    """Name -> [catalog, default] of every blok declared on `app`."""
    return {k: [b.catalog, b.default] for k, b in app.registry.get_declared_bloks().items()}


def newswitch_blok(content: str) -> str:
    """`content` as a panel blok written for the newswitch catalog."""
    return f'<Blok kind="agent" context="panel" catalog="newswitch">{content}</Blok>'


def orkestrator_blok(content: str) -> str:
    """`content` as a panel blok written for Orkestrator's catalog."""
    return f'<Blok kind="agent" context="panel" catalog="{ORKESTRATOR_CATALOG_ID}">{content}</Blok>'


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
        ("<StageView><NoSuchThing /></StageView>", "NoSuchThing"),
        # A scene layer draws into a canvas: it only stands inside a StageScene.
        ("<div><FramesLayer /></div>", "FramesLayer"),
        ('<SettingsPanel colour="red" />', "colour"),
        # A blok picks a colour role, never a palette colour.
        ('<div className="bg-red-500" />', "bg-red-500"),
        # The newswitch catalog extends the base alone: what only Orkestrator draws is not in it.
        ("<MikroScene />", "MikroScene"),
    ],
)
def test_a_blok_the_frontend_cannot_render_is_refused(tree: str, finding: str) -> None:
    """Strict checking refuses unknown components and props, and misplaced scene layers."""
    app = create_fastapi_registry(None)
    with pytest.raises(ValueError, match=finding):
        declare_bloks(
            app, "ui", {"broken": BlokEntry(bsx=newswitch_blok(tree))}, {CATALOG_NAME}, UI_TOLERATED
        )
    assert "broken" not in app.registry.get_declared_bloks()


def test_a_ui_blok_may_use_any_tailwind_class() -> None:
    """The frontend compiles Tailwind: a class beyond the portable subset is not refused."""
    app = create_fastapi_registry(None)
    view = BlokEntry(bsx=newswitch_blok('<div className="[&_svg]:size-4" />'))
    declare_bloks(app, "ui", {"view": view}, {CATALOG_NAME}, UI_TOLERATED)
    assert "view" in app.registry.get_declared_bloks()


@pytest.mark.parametrize(
    "bsx",
    [
        '<Blok kind="agent" context="panel"><div /></Blok>',
        orkestrator_blok("<div />"),
    ],
)
def test_a_ui_blok_names_the_newswitch_catalog(bsx: str) -> None:
    """The frontend draws the newswitch catalog: a ui blok written for another is refused."""
    app = create_fastapi_registry(None)
    with pytest.raises(ValueError, match="ui.bloks.view is written for"):
        declare_bloks(app, "ui", {"view": BlokEntry(bsx=bsx)}, {CATALOG_NAME})


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


# --- agent mode: the agent's own bloks, drawn with Orkestrator's module -------------------


def test_agent_mode_shows_its_own_bloks() -> None:
    """The agent's bloks ship with it: the same on every microscope, whatever it has, and they
    pass the base catalog and what the static app registers."""
    pytest.importorskip("lovekit")
    from app import app

    declared = app.registry.get_declared_bloks()
    assert set(declared) == set(AGENT_BLOKS)
    assert {"view-microscope", "view-acquire"} <= set(declared)
    assert {
        "test-stage",
        "test-detectors",
        "test-lights",
        "test-bus",
        "calibrate-holder",
        "acquire-lit",
        "test-speed",
    } <= set(declared)
    # Only the microscope view is shown first; the test views are there to pick.
    assert [name for name, blok in declared.items() if blok.default] == ["view-microscope"]
    # Written for the base catalog: it runs wherever bloks are drawn, Orkestrator among them.
    assert declared["view-microscope"].catalog is None and declared["view-microscope"].default
    assert declared["view-acquire"].catalog is None and not declared["view-acquire"].default
    # Declared by their files, so arkitekt check and the editor point into the .bsx.
    files = {name: blok.file for name, blok in app.registry.registered_bloks.items()}
    assert files == {name: str(entry.path) for name, entry in agent_bloks().items()}


def test_a_description_holds_no_agent_bloks(tmp_path: Path) -> None:
    """An ``agent_ui`` section is refused, saying where the agent's bloks are now."""
    copy = tmp_path / "instrument"
    copy.mkdir()
    description = (CAM_TEST / spec.DESCRIPTION).read_text()
    (copy / spec.DESCRIPTION).write_text(description + "agent_ui:\n  bloks: {}\n")
    for name in ("view.bsx",):
        (copy / name).write_text((CAM_TEST / name).read_text())
    with pytest.raises(spec.SpecError, match="ship with newswitch"):
        spec.load(copy)


def test_agent_mode_refuses_a_newswitch_component() -> None:
    """Orkestrator does not render the newswitch frontend's components."""
    pytest.importorskip("lovekit")
    import app as agent

    # A fresh app with what the agent's holds: the global one is not declared on from outside.
    app = App("newswitch", app_context=agent.Run)
    app.include(agent.app)
    broken = BlokEntry(bsx=orkestrator_blok("<StageControl />"))
    with pytest.raises(ValueError, match="StageControl"):
        declare_bloks(app, "agent", {"broken": broken}, AGENT_CATALOGS)


def test_an_agent_blok_is_not_written_for_the_newswitch_catalog() -> None:
    """Orkestrator does not hold the newswitch catalog: a blok written for it is refused."""
    app = create_fastapi_registry(None)
    view = BlokEntry(bsx=newswitch_blok("<div />"))
    with pytest.raises(ValueError, match="agent.bloks.view is written for 'newswitch'"):
        declare_bloks(app, "agent", {"view": view}, AGENT_CATALOGS)


# --- what a blok reads ---------------------------------------------------------------------------


def test_a_blok_reading_what_the_app_lacks_is_refused() -> None:
    """What a blok reads of ``self`` is checked against the app as it is declared: a state by
    its class name, a field gone. Every instrument's views pass it
    (``test_instrument_server.py::test_every_instruments_bloks_can_be_served``)."""
    app = create_fastapi_registry(None)
    view = BlokEntry(bsx=newswitch_blok("<div>{self.DetectorState.is_acquiring}</div>"))
    with pytest.raises(ValueError, match="DetectorState"):
        declare_bloks(app, "ui", {"view": view}, {CATALOG_NAME}, UI_TOLERATED)
