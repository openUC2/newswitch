"""The UI the backend declares: the newswitch blok catalog and the bloks built in it.

`declare_ui` declares the catalog, the bloks every setup has (``jonda``), and the views
the frontend's bottom bar switches between (bloks keyed ``view-…``, whose description
starts with their tab's label). `ImswitchConfig.ui` chooses the set and the view shown
first: ``standard`` (Standard, Minimal), ``minimal`` (Minimal, Standard) or ``design``
(3D, Stage, Minimal: a microscope described by an optikit design, see
`newswitch.bloks.design`).

`nsapp` is one per process, so the UI is declared once: `create_app` calls this before
serving, and a second call with the same choice does nothing.
"""

from newswitch.bloks.catalog import CATALOG_FILE, CATALOG_NAME, declare_catalog
from newswitch.config_io import adapters
from newswitch.config import ImswitchConfig

__all__ = ["CATALOG_FILE", "CATALOG_NAME", "declare_ui"]

_declared: tuple[str, str | None] | None = None


def declare_ui(config: ImswitchConfig) -> None:
    """Declare the catalog and the UI `config` chooses.

    Raises:
        RuntimeError: A different UI was already declared in this process.
    """
    global _declared
    choice = (config.ui, str(config.design) if config.ui == "design" else None)
    if _declared is not None:
        if _declared != choice:
            raise RuntimeError(
                f"the UI {_declared[0]!r} is declared already; a process serves one UI"
            )
        return

    declare_catalog()
    from newswitch.bloks import fluorescence, jonda, minimal, standard, stage_view  # noqa: F401

    # The views the bottom bar switches between; `ui` chooses the one shown first.
    if config.ui == "design":
        from newswitch.bloks import design
        from newswitch.design.config import design_config

        assert config.design is not None  # ImswitchConfig refuses ui=design without one
        devices = design_config(config.design)
        design.declare(config.design, devices, CATALOG_NAME)
        fluorescence.declare(CATALOG_NAME, has_filters=adapters.filters(devices) is not None)
        stage_view.declare(default=False)
        minimal.declare(default=False)
    else:
        standard.declare(default=config.ui == "standard")
        minimal.declare(default=config.ui == "minimal")
    _declared = choice
