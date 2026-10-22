"""The UI the backend declares: the newswitch catalog and the standard blok in it."""

import pytest
from arkitekt import bsx

import newswitch.app  # noqa: F401  (declares everything on nsapp)
from newswitch.arkitekt_app import nsapp
from newswitch.bloks import CATALOG_NAME, declare_ui
from newswitch.config import ImswitchConfig

# The standard UI, as every app the other tests create declares it.
declare_ui(ImswitchConfig(config_file=None))


def test_the_standard_blok_is_the_default_ui_in_the_newswitch_catalog() -> None:
    """The frontend shows `view-standard` first: the one default HTML blok, in the newswitch catalog."""
    bloks = nsapp.registry.get_declared_bloks()

    standard = bloks["view-standard"]
    assert standard.catalog == CATALOG_NAME
    assert standard.context == "HTML"
    assert standard.default is True
    defaults = [key for key, blok in bloks.items() if blok.default and blok.context == "HTML"]
    assert defaults == ["view-standard"]
    # The views the bottom bar switches between.
    assert {"view-standard", "view-minimal"} <= set(bloks)


@pytest.mark.parametrize(
    "tree, finding",
    [
        ("<StageView><NoSuchThing /></StageView>", "NoSuchThing"),
        # A scene layer draws into a canvas: it only stands inside a StageScene.
        ("<div><FramesLayer /></div>", "FramesLayer"),
        ("<SettingsPanel colour='red' />", "colour"),
    ],
)
def test_a_blok_the_frontend_cannot_render_is_refused(tree: str, finding: str) -> None:
    """Strict checking refuses unknown components and props, and misplaced scene layers."""
    with pytest.raises(ValueError, match=finding):
        nsapp.blok("broken", bsx(tree), catalog=CATALOG_NAME, mode="strict")
    assert "broken" not in nsapp.registry.get_declared_bloks()


def test_a_process_serves_one_ui() -> None:
    """Declaring another UI after one was declared is refused; the same one is a no-op."""
    declare_ui(ImswitchConfig(config_file=None))
    with pytest.raises(RuntimeError, match="one UI"):
        declare_ui(ImswitchConfig(config_file=None, ui="minimal"))
